"""通知管理サービス"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_log import NotificationLog
from app.api.sse import broadcast_event

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    event_type: str,
    message: str,
    reservation_id: int | None = None,
    extra_data: dict | None = None,
):
    """通知を作成しSSEでブロードキャスト"""
    notif = NotificationLog(
        reservation_id=reservation_id,
        event_type=event_type,
        message=message,
    )
    db.add(notif)
    await db.flush()

    payload = {
        "id": notif.id,
        "reservation_id": reservation_id,
        "event_type": event_type,
        "message": message,
    }
    if extra_data:
        payload.update(extra_data)

    await broadcast_event(event_type, payload)

    return notif
