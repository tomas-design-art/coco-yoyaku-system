"""院営業スケジュールAPI"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.auth import require_admin
from app.models.weekly_schedule import WeeklySchedule
from app.schemas.weekly_schedule import WeeklyScheduleUpdate, WeeklyScheduleResponse

router = APIRouter(prefix="/api/weekly-schedules", tags=["weekly-schedules"])


@router.get("/", response_model=list[WeeklyScheduleResponse])
async def list_schedules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(WeeklySchedule).order_by(WeeklySchedule.day_of_week)
    )
    return result.scalars().all()


@router.put("/{day_of_week}", response_model=WeeklyScheduleResponse)
async def update_schedule(
    day_of_week: int,
    data: WeeklyScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    _auth: dict = Depends(require_admin),
):
    if day_of_week < 0 or day_of_week > 6:
        raise HTTPException(status_code=400, detail="day_of_week は 0〜6 の範囲で指定してください")

    result = await db.execute(
        select(WeeklySchedule).where(WeeklySchedule.day_of_week == day_of_week)
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        schedule = WeeklySchedule(
            day_of_week=day_of_week,
            is_open=data.is_open,
            open_time=data.open_time,
            close_time=data.close_time,
        )
        db.add(schedule)
    else:
        schedule.is_open = data.is_open
        schedule.open_time = data.open_time
        schedule.close_time = data.close_time

    await db.commit()
    await db.refresh(schedule)
    return schedule
