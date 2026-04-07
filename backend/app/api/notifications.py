from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.notification_log import NotificationLog
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    id: int
    reservation_id: Optional[int] = None
    event_type: str
    message: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[NotificationResponse])
async def list_notifications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationLog).order_by(
            NotificationLog.is_read, NotificationLog.created_at.desc()
        ).limit(50)
    )
    return result.scalars().all()


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(notification_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationLog).where(NotificationLog.id == notification_id)
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="通知が見つかりません")
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return notif
