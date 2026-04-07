"""院営業時間API — 日付レンジで解決済み営業時間を返す"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.business_hours import get_business_hours_for_date

router = APIRouter(prefix="/api/business-hours", tags=["business-hours"])


@router.get("/range")
async def get_business_hours_range(
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """日付レンジの営業時間を一括取得 (override → 祝日 → 曜日 → fallback)"""
    sd = date.fromisoformat(start_date)
    ed = date.fromisoformat(end_date)

    results = []
    current = sd
    while current <= ed:
        bh = await get_business_hours_for_date(db, current)
        results.append({
            "date": current.isoformat(),
            "is_open": bh.is_open,
            "open_time": bh.open_time,
            "close_time": bh.close_time,
            "source": bh.source,
            "label": bh.label,
        })
        current += timedelta(days=1)

    return results
