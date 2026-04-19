"""競合検出ロジック"""
import logging
from datetime import datetime

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.reservation import Reservation

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("CONFIRMED", "HOLD", "PENDING")


async def get_conflicting_reservations(
    db: AsyncSession,
    practitioner_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_reservation_id: int | None = None,
) -> list[Reservation]:
    """同一施術者の同時間帯に存在するアクティブな予約を返す"""
    query = select(Reservation).where(
        and_(
            Reservation.practitioner_id == practitioner_id,
            Reservation.status.in_(ACTIVE_STATUSES),
            Reservation.start_time < end_time,
            Reservation.end_time > start_time,
        )
    ).options(selectinload(Reservation.patient), selectinload(Reservation.practitioner))
    if exclude_reservation_id:
        query = query.where(Reservation.id != exclude_reservation_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def check_conflict(
    db: AsyncSession,
    practitioner_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_reservation_id: int | None = None,
) -> list[Reservation]:
    """競合チェック。競合がある場合は競合予約リストを返す"""
    return await get_conflicting_reservations(
        db, practitioner_id, start_time, end_time, exclude_reservation_id
    )


async def get_patient_conflicting_reservations(
    db: AsyncSession,
    patient_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_reservation_id: int | None = None,
) -> list[Reservation]:
    """同一患者が同時間帯に既に予約されているかチェック"""
    query = select(Reservation).where(
        and_(
            Reservation.patient_id == patient_id,
            Reservation.status.in_(ACTIVE_STATUSES),
            Reservation.start_time < end_time,
            Reservation.end_time > start_time,
        )
    ).options(selectinload(Reservation.patient), selectinload(Reservation.practitioner))
    if exclude_reservation_id:
        query = query.where(Reservation.id != exclude_reservation_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def check_patient_conflict(
    db: AsyncSession,
    patient_id: int | None,
    start_time: datetime,
    end_time: datetime,
    exclude_reservation_id: int | None = None,
) -> list[Reservation]:
    """同一患者の時間重複チェック。patient_id が None の場合は空リストを返す"""
    if not patient_id:
        return []
    return await get_patient_conflicting_reservations(
        db, patient_id, start_time, end_time, exclude_reservation_id
    )
