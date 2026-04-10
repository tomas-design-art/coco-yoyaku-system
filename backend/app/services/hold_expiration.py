"""HOLD自動失効ジョブ + チャットセッション自動expire + HP枠押さえリマインド + 通知ログ自動削除"""
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models.reservation import Reservation
from app.models.chat_session import ChatSession
from app.models.notification_log import NotificationLog
from app.services.notification_service import create_notification
from app.utils.datetime_jst import now_jst

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_HOTPEPPER_POLL_FAILURE_STREAK = 0


async def expire_holds():
    """期限切れのHOLD予約をEXPIREDに更新"""
    async with async_session() as db:
        now = now_jst()
        result = await db.execute(
            select(Reservation).where(
                Reservation.status == "HOLD",
                Reservation.hold_expires_at < now,
            )
        )
        expired = result.scalars().all()
        for reservation in expired:
            reservation.status = "EXPIRED"
            await create_notification(
                db,
                "hold_expired",
                f"HOLD期限切れ: 予約#{reservation.id}",
                reservation.id,
            )
            logger.info(f"HOLD expired: reservation #{reservation.id}")
        if expired:
            await db.commit()
            logger.info(f"Expired {len(expired)} HOLD reservations")


async def expire_chat_sessions():
    """24時間以上経過したチャットセッションをexpireする"""
    async with async_session() as db:
        cutoff = now_jst() - timedelta(hours=24)
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.status == "active",
                ChatSession.created_at < cutoff,
            )
        )
        sessions = result.scalars().all()
        for s in sessions:
            s.status = "expired"
            logger.info(f"Chat session expired: {s.id}")
        if sessions:
            await db.commit()
            logger.info(f"Expired {len(sessions)} chat sessions")


async def remind_hotpepper_sync():
    """HP未押さえ予約のリマインド通知（30分間隔）"""
    async with async_session() as db:
        result = await db.execute(
            select(Reservation)
            .where(
                Reservation.hotpepper_synced == False,
                Reservation.channel != "HOTPEPPER",
                Reservation.status.in_(["CONFIRMED", "PENDING", "HOLD"]),
            )
            .options(selectinload(Reservation.patient))
            .order_by(Reservation.start_time)
        )
        unsynced = result.scalars().all()
        if unsynced:
            count = len(unsynced)
            logger.info(f"HP sync reminder: {count} unsynced reservations")
            await create_notification(
                db,
                "hotpepper_sync_reminder",
                f"HotPepper未押さえの予約が {count} 件あります。HP同期画面で確認してください。",
            )
            await db.commit()


async def cleanup_old_notifications():
    """一定期間を超えた通知ログを自動削除"""
    async with async_session() as db:
        read_retention_days = max(1, settings.notification_retention_days)
        unread_retention_days = max(1, settings.notification_unread_retention_days)

        cutoff = now_jst() - timedelta(days=read_retention_days)
        result = await db.execute(
            delete(NotificationLog).where(
                NotificationLog.is_read == True,
                NotificationLog.created_at < cutoff,
            )
        )
        deleted = result.rowcount
        if deleted:
            await db.commit()
            logger.info(
                "Cleaned up %s old read notifications (>%s days)",
                deleted,
                read_retention_days,
            )

        cutoff_unread = now_jst() - timedelta(days=unread_retention_days)
        result2 = await db.execute(
            delete(NotificationLog).where(
                NotificationLog.is_read == False,
                NotificationLog.created_at < cutoff_unread,
            )
        )
        deleted2 = result2.rowcount
        if deleted2:
            await db.commit()
            logger.info(
                "Cleaned up %s old unread notifications (>%s days)",
                deleted2,
                unread_retention_days,
            )


async def poll_hotpepper_mail_job():
    """HotPepperメールの定期ポーリング"""
    from app.services.hotpepper_mail import poll_hotpepper_mail_once
    from app.services.line_alerts import push_developer_sos_alert, push_developer_recovered_alert
    global _HOTPEPPER_POLL_FAILURE_STREAK
    incident_key = "hotpepper_poll_incident"
    try:
        result = await poll_hotpepper_mail_once()
        logger.info("HotPepper poll result: %s", result)

        if isinstance(result, dict) and result.get("status") == "error":
            _HOTPEPPER_POLL_FAILURE_STREAK += 1
            await push_developer_sos_alert(
                "HotPepperメール取得に失敗しました",
                detail=str(result),
                source="hotpepper_poll",
                error_type="PollErrorStatus",
                failure_streak=_HOTPEPPER_POLL_FAILURE_STREAK,
                dedupe_key=incident_key,
            )
        else:
            if _HOTPEPPER_POLL_FAILURE_STREAK > 0:
                await push_developer_recovered_alert(
                    dedupe_key=incident_key,
                    title="HotPepperメール取得が復旧しました",
                    source="hotpepper_poll",
                    latest_detail=str(result),
                )
            _HOTPEPPER_POLL_FAILURE_STREAK = 0
    except Exception as e:
        _HOTPEPPER_POLL_FAILURE_STREAK += 1
        logger.exception("HotPepper poll job crashed: %s", e)
        await push_developer_sos_alert(
            "HotPepperポーリング処理で例外が発生しました",
            detail=str(e),
            source="hotpepper_poll_job",
            error_type=type(e).__name__,
            failure_streak=_HOTPEPPER_POLL_FAILURE_STREAK,
            dedupe_key=incident_key,
        )


def start_hold_expiration_job():
    scheduler.add_job(expire_holds, "interval", minutes=1, id="hold_expiration")
    scheduler.add_job(expire_chat_sessions, "interval", minutes=10, id="chat_session_expiration")
    scheduler.add_job(remind_hotpepper_sync, "interval", minutes=30, id="hotpepper_sync_reminder")
    scheduler.add_job(
        poll_hotpepper_mail_job,
        "interval",
        minutes=max(1, settings.hotpepper_poll_interval_minutes),
        id="hotpepper_mail_poll",
    )
    scheduler.add_job(cleanup_old_notifications, "cron", hour=3, minute=0, id="notification_cleanup")
    scheduler.start()
    logger.info(
        "Background jobs started (HOLD expiration, chat session expiration, HP sync reminder, HotPepper mail poll, notification cleanup)"
    )


def stop_hold_expiration_job():
    scheduler.shutdown(wait=False)
    logger.info("HOLD expiration job stopped")
