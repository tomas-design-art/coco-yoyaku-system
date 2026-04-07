"""予約API"""
from datetime import date, datetime, timedelta
from typing import Optional
import zoneinfo
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.reservation import Reservation
from app.schemas.reservation import (
    ReservationCreate,
    ReservationResponse,
    ReservationUpdate,
    ChangeRequestBody,
    RescheduleBody,
    BulkReservationCreate,
    BulkReservationResult,
)
from app.services.reservation_service import (
    create_reservation,
    transition_status,
    handle_change_request,
    handle_change_approve,
    reschedule_reservation,
    build_reservation_response,
)
from app.services.conflict_detector import check_conflict, ACTIVE_STATUSES
from app.services.notification_service import create_notification

_JST = zoneinfo.ZoneInfo("Asia/Tokyo")
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reservations", tags=["reservations"])


@router.get("/conflicts")
async def list_conflicts(db: AsyncSession = Depends(get_db)):
    """競合予約一覧"""
    result = await db.execute(
        select(Reservation)
        .where(Reservation.conflict_note.isnot(None))
        .options(
            selectinload(Reservation.patient),
            selectinload(Reservation.practitioner),
            selectinload(Reservation.menu),
            selectinload(Reservation.color),
        )
        .order_by(Reservation.created_at.desc())
        .limit(50)
    )
    reservations = result.scalars().all()
    return [build_reservation_response(r) for r in reservations]


@router.get("/", response_model=list[ReservationResponse])
async def list_reservations(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    practitioner_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(Reservation).options(
        selectinload(Reservation.patient),
        selectinload(Reservation.practitioner),
        selectinload(Reservation.menu),
        selectinload(Reservation.color),
    )

    if start_date:
        start = datetime.fromisoformat(start_date + "T00:00:00+09:00")
        query = query.where(Reservation.end_time >= start)
    if end_date:
        end = datetime.fromisoformat(end_date + "T23:59:59+09:00")
        query = query.where(Reservation.start_time <= end)
    if practitioner_id:
        query = query.where(Reservation.practitioner_id == practitioner_id)

    query = query.order_by(Reservation.start_time)
    result = await db.execute(query)
    reservations = result.scalars().all()
    return [build_reservation_response(r) for r in reservations]


@router.get("/{reservation_id}")
async def get_reservation(reservation_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .options(
            selectinload(Reservation.patient),
            selectinload(Reservation.practitioner),
            selectinload(Reservation.menu),
            selectinload(Reservation.color),
        )
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="予約が見つかりません")
    return build_reservation_response(reservation)


@router.post("/", status_code=201)
async def create_reservation_endpoint(
    data: ReservationCreate, db: AsyncSession = Depends(get_db)
):
    return await create_reservation(db, data)


def _generate_dates(start_date: date, frequency: str, end_date: date | None, count: int | None) -> list[date]:
    """繰り返し日付リストを生成（最大52週=約1年）"""
    MAX_COUNT = 52
    dates: list[date] = []
    current = start_date
    limit = count if count else MAX_COUNT

    for _ in range(limit):
        if end_date and current > end_date:
            break
        dates.append(current)
        if frequency == "weekly":
            current += timedelta(days=7)
        elif frequency == "biweekly":
            current += timedelta(days=14)
        elif frequency == "monthly":
            # 同日翌月（月末は調整）
            month = current.month % 12 + 1
            year = current.year + (1 if current.month == 12 else 0)
            day = min(current.day, 28)  # 安全策: 29-31 → 28
            current = current.replace(year=year, month=month, day=day)
    return dates


@router.post("/bulk", status_code=201)
async def bulk_create_reservations(
    data: BulkReservationCreate, db: AsyncSession = Depends(get_db)
):
    """繰り返し予約一括生成"""
    if not data.end_date and not data.count:
        raise HTTPException(status_code=400, detail="end_date または count を指定してください")

    dates = _generate_dates(data.start_date, data.frequency, data.end_date, data.count)
    if not dates:
        raise HTTPException(status_code=400, detail="生成対象の日付がありません")

    created_count = 0
    skipped: list[dict] = []

    hour, minute = map(int, data.start_time.split(":"))

    for target_date in dates:
        start_dt = datetime(
            target_date.year, target_date.month, target_date.day,
            hour, minute, tzinfo=_JST,
        )
        end_dt = start_dt + timedelta(minutes=data.duration_minutes)

        reservation_data = ReservationCreate(
            patient_id=data.patient_id,
            practitioner_id=data.practitioner_id,
            menu_id=data.menu_id,
            color_id=data.color_id,
            start_time=start_dt,
            end_time=end_dt,
            channel=data.channel,
            notes=data.notes,
        )
        try:
            await create_reservation(db, reservation_data)
            created_count += 1
        except HTTPException as e:
            skipped.append({"date": target_date.isoformat(), "reason": e.detail})
        except Exception as e:
            logger.error("Bulk reservation error on %s: %s", target_date, e)
            skipped.append({"date": target_date.isoformat(), "reason": "内部エラー"})

    return BulkReservationResult(
        total_requested=len(dates),
        created_count=created_count,
        skipped=skipped,
    )


@router.put("/{reservation_id}")
async def update_reservation(
    reservation_id: int, data: ReservationUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Reservation).where(Reservation.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="予約が見つかりません")

    update_data = data.model_dump(exclude_unset=True)

    # 時間・施術者変更時は競合チェック
    new_start = update_data.get("start_time", reservation.start_time)
    new_end = update_data.get("end_time", reservation.end_time)
    new_prac = update_data.get("practitioner_id", reservation.practitioner_id)
    time_or_prac_changed = (
        "start_time" in update_data
        or "end_time" in update_data
        or "practitioner_id" in update_data
    )
    if time_or_prac_changed and reservation.status in ACTIVE_STATUSES:
        conflicts = await check_conflict(
            db, new_prac, new_start, new_end,
            exclude_reservation_id=reservation_id,
        )
        if conflicts:
            conflict_names = []
            for c in conflicts:
                name = c.patient.name if c.patient else "不明"
                conflict_names.append(
                    f"{name}({c.start_time.strftime('%H:%M')}-{c.end_time.strftime('%H:%M')})"
                )
            raise HTTPException(
                status_code=409,
                detail=f"予約が競合しています: {', '.join(conflict_names)}",
            )

    for key, value in update_data.items():
        setattr(reservation, key, value)
    await db.commit()
    result2 = await db.execute(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .options(
            selectinload(Reservation.patient),
            selectinload(Reservation.practitioner),
            selectinload(Reservation.menu),
            selectinload(Reservation.color),
        )
    )
    reservation = result2.scalar_one()
    return build_reservation_response(reservation)


@router.post("/{reservation_id}/confirm")
async def confirm_reservation(reservation_id: int, db: AsyncSession = Depends(get_db)):
    reservation = await transition_status(db, reservation_id, "CONFIRMED")
    await create_notification(
        db, "reservation_confirmed",
        f"予約確定: 予約#{reservation_id}",
        reservation_id,
    )
    await db.commit()
    result = await db.execute(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .options(
            selectinload(Reservation.patient),
            selectinload(Reservation.practitioner),
            selectinload(Reservation.menu),
            selectinload(Reservation.color),
        )
    )
    reservation = result.scalar_one()
    return build_reservation_response(reservation)


@router.post("/{reservation_id}/reject")
async def reject_reservation(reservation_id: int, db: AsyncSession = Depends(get_db)):
    reservation = await transition_status(db, reservation_id, "REJECTED")
    await create_notification(
        db, "reservation_rejected",
        f"予約却下: 予約#{reservation_id}",
        reservation_id,
    )
    await db.commit()
    result = await db.execute(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .options(
            selectinload(Reservation.patient),
            selectinload(Reservation.practitioner),
            selectinload(Reservation.menu),
            selectinload(Reservation.color),
        )
    )
    reservation = result.scalar_one()
    return build_reservation_response(reservation)


@router.post("/{reservation_id}/cancel-request")
async def cancel_request(reservation_id: int, db: AsyncSession = Depends(get_db)):
    reservation = await transition_status(db, reservation_id, "CANCEL_REQUESTED")
    await create_notification(
        db, "cancel_requested",
        f"キャンセル申請: 予約#{reservation_id}",
        reservation_id,
    )
    await db.commit()
    result = await db.execute(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .options(
            selectinload(Reservation.patient),
            selectinload(Reservation.practitioner),
            selectinload(Reservation.menu),
            selectinload(Reservation.color),
        )
    )
    reservation = result.scalar_one()
    return build_reservation_response(reservation)


@router.post("/{reservation_id}/cancel-approve")
async def cancel_approve(reservation_id: int, db: AsyncSession = Depends(get_db)):
    reservation = await transition_status(db, reservation_id, "CANCELLED")
    is_hotpepper = reservation.channel == "HOTPEPPER"
    await create_notification(
        db, "cancel_approved",
        f"キャンセル承認: 予約#{reservation_id}",
        reservation_id,
    )
    if is_hotpepper:
        await create_notification(
            db, "hotpepper_cancel_remind",
            f"HotPepper側もキャンセルしてください: 予約#{reservation_id}",
            reservation_id,
        )
    await db.commit()
    result = await db.execute(
        select(Reservation)
        .where(Reservation.id == reservation_id)
        .options(
            selectinload(Reservation.patient),
            selectinload(Reservation.practitioner),
            selectinload(Reservation.menu),
            selectinload(Reservation.color),
        )
    )
    reservation = result.scalar_one()
    return build_reservation_response(reservation)


@router.post("/{reservation_id}/change-request")
async def change_request(
    reservation_id: int,
    body: ChangeRequestBody,
    db: AsyncSession = Depends(get_db),
):
    return await handle_change_request(
        db, reservation_id,
        body.new_start_time, body.new_end_time,
        body.new_practitioner_id,
    )


@router.post("/{reservation_id}/change-approve")
async def change_approve(reservation_id: int, db: AsyncSession = Depends(get_db)):
    return await handle_change_approve(db, reservation_id)


@router.post("/{reservation_id}/reschedule")
async def reschedule(reservation_id: int, body: RescheduleBody, db: AsyncSession = Depends(get_db)):
    return await reschedule_reservation(
        db, reservation_id,
        body.new_start_time, body.new_end_time,
        body.new_practitioner_id,
    )
