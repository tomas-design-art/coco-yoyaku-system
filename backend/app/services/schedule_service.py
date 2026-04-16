"""職員勤務スケジュール判定サービス"""
import logging
from datetime import date, datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.practitioner_schedule import PractitionerSchedule, ScheduleOverride
from app.models.practitioner import Practitioner
from app.models.practitioner_unavailable_time import PractitionerUnavailableTime
from app.models.reservation import Reservation
from app.models.weekly_schedule import WeeklySchedule
from app.services.conflict_detector import ACTIVE_STATUSES
from app.services.business_hours import get_business_hours_for_date

logger = logging.getLogger(__name__)


async def is_practitioner_working(
    db: AsyncSession,
    practitioner_id: int,
    target_date: date,
) -> tuple[bool, str | None, str]:
    """
    施術者がその日に出勤しているか判定する。
    Returns: (is_working, reason, source)
    source: "override" | "default" | "fallback"
    """
    # 1. override を優先チェック
    result = await db.execute(
        select(ScheduleOverride).where(
            and_(
                ScheduleOverride.practitioner_id == practitioner_id,
                ScheduleOverride.date == target_date,
            )
        )
    )
    override = result.scalar_one_or_none()
    if override:
        return override.is_working, override.reason, "override"

    # 2. デフォルトパターン
    # JS getDay(): 0=日,1=月...6=土 → DB: 0=日,1=月...6=土
    dow = target_date.isoweekday() % 7  # Mon=1..Sun=7 → Sun=0,Mon=1..Sat=6
    result = await db.execute(
        select(PractitionerSchedule).where(
            and_(
                PractitionerSchedule.practitioner_id == practitioner_id,
                PractitionerSchedule.day_of_week == dow,
            )
        )
    )
    schedule = result.scalar_one_or_none()
    if schedule:
        return schedule.is_working, None, "default"

    # 3. 個人レコードなし → 院営業スケジュールに連動（祝日・override 考慮）
    bh = await get_business_hours_for_date(db, target_date)
    if not bh.is_open:
        reason = bh.label or "院休業日"
        return False, reason, "clinic"
    return True, None, "clinic"


async def get_practitioner_working_hours(
    db: AsyncSession,
    practitioner_id: int,
    target_date: date,
) -> tuple[str | None, str | None]:
    """
    施術者のその日の勤務開始/終了時刻を返す。
    Returns: (start_time "HH:MM" or None, end_time "HH:MM" or None)
    出勤していない場合や時刻情報がない場合は (None, None)。
    """
    is_working, _, source = await is_practitioner_working(db, practitioner_id, target_date)
    if not is_working:
        return None, None

    dow = target_date.isoweekday() % 7
    if source == "default":
        result = await db.execute(
            select(PractitionerSchedule).where(
                and_(
                    PractitionerSchedule.practitioner_id == practitioner_id,
                    PractitionerSchedule.day_of_week == dow,
                )
            )
        )
        s = result.scalar_one_or_none()
        if s:
            return s.start_time, s.end_time

    # override / clinic → 院営業時間にフォールバック
    bh = await get_business_hours_for_date(db, target_date)
    if bh.is_open and bh.open_time and bh.close_time:
        return bh.open_time, bh.close_time
    return None, None


async def get_practitioner_day_status(
    db: AsyncSession,
    practitioner_id: int,
    target_date: date,
) -> dict:
    """施術者の日別ステータスを取得"""
    is_working, reason, source = await is_practitioner_working(db, practitioner_id, target_date)

    result = {"practitioner_id": practitioner_id, "date": target_date, "is_working": is_working, "reason": reason, "source": source}

    # 勤務時間を取得 (全source共通)
    if is_working:
        wh_start, wh_end = await get_practitioner_working_hours(db, practitioner_id, target_date)
        if wh_start:
            result["start_time"] = wh_start
        if wh_end:
            result["end_time"] = wh_end

    # 時間帯休み
    ut_result = await db.execute(
        select(PractitionerUnavailableTime).where(
            and_(
                PractitionerUnavailableTime.practitioner_id == practitioner_id,
                PractitionerUnavailableTime.date == target_date,
            )
        ).order_by(PractitionerUnavailableTime.start_time)
    )
    unavailable_times = ut_result.scalars().all()
    if unavailable_times:
        result["unavailable_times"] = [
            {"id": ut.id, "start_time": ut.start_time, "end_time": ut.end_time, "reason": ut.reason}
            for ut in unavailable_times
        ]

    return result


async def get_affected_reservations(
    db: AsyncSession,
    practitioner_id: int,
    target_date: date,
) -> list[Reservation]:
    """指定施術者の指定日のアクティブ予約を取得"""
    start_dt = datetime.fromisoformat(f"{target_date}T00:00:00+09:00")
    end_dt = datetime.fromisoformat(f"{target_date}T23:59:59+09:00")

    result = await db.execute(
        select(Reservation).where(
            and_(
                Reservation.practitioner_id == practitioner_id,
                Reservation.status.in_(ACTIVE_STATUSES),
                Reservation.start_time >= start_dt,
                Reservation.start_time <= end_dt,
            )
        ).options(
            selectinload(Reservation.patient),
            selectinload(Reservation.menu),
            selectinload(Reservation.practitioner),
        ).order_by(Reservation.start_time)
    )
    return list(result.scalars().all())


async def find_transfer_candidates(
    db: AsyncSession,
    practitioner_id: int,
    target_date: date,
    start_time: datetime,
    end_time: datetime,
) -> list[dict]:
    """
    同日同時間帯で振替可能な他の施術者を検索
    """
    # アクティブな施術者を取得 (対象を除く)
    result = await db.execute(
        select(Practitioner).where(
            and_(
                Practitioner.is_active == True,
                Practitioner.id != practitioner_id,
            )
        ).order_by(Practitioner.display_order)
    )
    other_practitioners = list(result.scalars().all())

    candidates = []
    for p in other_practitioners:
        # その日出勤しているか
        working, _, _ = await is_practitioner_working(db, p.id, target_date)
        if not working:
            candidates.append({"practitioner_id": p.id, "practitioner_name": p.name, "is_available": False})
            continue

        # 時間帯に既存予約があるか
        conflict_result = await db.execute(
            select(Reservation).where(
                and_(
                    Reservation.practitioner_id == p.id,
                    Reservation.status.in_(ACTIVE_STATUSES),
                    Reservation.start_time < end_time,
                    Reservation.end_time > start_time,
                )
            )
        )
        has_conflict = conflict_result.scalar_one_or_none() is not None
        candidates.append({"practitioner_id": p.id, "practitioner_name": p.name, "is_available": not has_conflict})

    return candidates
