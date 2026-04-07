"""HotPepper関連API"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.reservation import Reservation
from app.services.reservation_service import build_reservation_response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hotpepper", tags=["hotpepper"])


class ParseEmailRequest(BaseModel):
    email_body: str


class ParseEmailResponse(BaseModel):
    customer_name: str | None = None
    reservation_date: str | None = None
    reservation_time: str | None = None
    menu_name: str | None = None
    duration_minutes: int | None = None
    reservation_number: str | None = None


@router.get("/pending-sync")
async def pending_sync(db: AsyncSession = Depends(get_db)):
    """HotPepper側未押さえの予約一覧"""
    result = await db.execute(
        select(Reservation)
        .where(
            Reservation.hotpepper_synced == False,
            Reservation.channel != "HOTPEPPER",
            Reservation.status.in_(["CONFIRMED", "PENDING", "HOLD"]),
        )
        .options(
            selectinload(Reservation.patient),
            selectinload(Reservation.practitioner),
            selectinload(Reservation.menu),
        )
        .order_by(Reservation.start_time)
    )
    reservations = result.scalars().all()
    return [build_reservation_response(r) for r in reservations]


@router.post("/{reservation_id}/mark-synced")
async def mark_synced(reservation_id: int, db: AsyncSession = Depends(get_db)):
    """HP側押さえ済みマーク"""
    result = await db.execute(
        select(Reservation).where(Reservation.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="予約が見つかりません")
    reservation.hotpepper_synced = True
    await db.commit()
    return {"status": "ok", "reservation_id": reservation_id}


@router.post("/parse-email", response_model=ParseEmailResponse)
async def parse_email(body: ParseEmailRequest, db: AsyncSession = Depends(get_db)):
    """HotPepperメール解析（テスト用手動解析）"""
    from app.agents.mail_parser import parse_hotpepper_email
    try:
        result = await parse_hotpepper_email(body.email_body)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"メール解析に失敗しました: {str(e)}")


@router.post("/receive-email")
async def receive_email(body: ParseEmailRequest, db: AsyncSession = Depends(get_db)):
    """HotPepperメールを受信して予約登録/更新/キャンセルする。

    手動投入 or 将来のIMAP/Gmailポーリングから呼ばれる共通エントリーポイント。
    event_type に応じて created / cancelled / changed を自動判定して処理する。
    """
    from app.services.hotpepper_mail import process_hotpepper_email
    try:
        result = await process_hotpepper_email(db, body.email_body)
        return result
    except Exception as e:
        logger.error(f"HotPepperメール処理エラー: {e}")
        raise HTTPException(status_code=500, detail=f"メール処理に失敗しました: {str(e)}")


@router.post("/trigger-poll")
async def trigger_poll(db: AsyncSession = Depends(get_db)):
    """手動ポーリング実行"""
    from app.services.hotpepper_mail import poll_hotpepper_mail_once

    try:
        result = await poll_hotpepper_mail_once()
        return result
    except Exception as e:
        logger.exception("HotPepper poll trigger failed: %s", e)
        raise HTTPException(status_code=500, detail=f"ポーリングに失敗しました: {str(e)}")
