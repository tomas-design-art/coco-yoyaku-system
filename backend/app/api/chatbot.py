"""チャットボットAPIエンドポイント"""
import uuid
import logging

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting
from app.services.chatbot_service import (
    create_session,
    get_session,
    process_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chatbot", tags=["chatbot"])


async def _require_chatbot_enabled(db: AsyncSession):
    result = await db.execute(select(Setting).where(Setting.key == "chatbot_enabled"))
    s = result.scalar_one_or_none()
    if s and s.value.lower() == "false":
        raise HTTPException(status_code=503, detail="チャットボットは現在停止中です")


class ChatMessageRequest(BaseModel):
    session_id: str = Field(..., description="セッションID (UUID)")
    message: str = Field(..., min_length=1, max_length=2000, description="ユーザーメッセージ")


class ChatSessionResponse(BaseModel):
    session_id: str
    messages: list[dict]
    status: str


class ChatMessageResponse(BaseModel):
    session_id: str
    response: str
    actions: list[dict] = []
    reservation_created: dict | None = None


@router.post("/session", response_model=ChatSessionResponse)
async def create_chat_session(db: AsyncSession = Depends(get_db)):
    """新規チャットセッションを作成"""
    await _require_chatbot_enabled(db)
    session = await create_session(db)
    return ChatSessionResponse(
        session_id=str(session.id),
        messages=session.messages,
        status=session.status,
    )


@router.get("/session/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """セッション履歴取得"""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="無効なセッションIDです")

    session = await get_session(db, sid)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    return ChatSessionResponse(
        session_id=str(session.id),
        messages=session.messages,
        status=session.status,
    )


@router.post("/message", response_model=ChatMessageResponse)
async def send_message(
    body: ChatMessageRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """チャットメッセージを送信してAI応答を取得"""
    try:
        sid = uuid.UUID(body.session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="無効なセッションIDです")

    client_ip = request.client.host if request.client else "unknown"

    result = await process_message(db, sid, body.message, client_ip)
    return ChatMessageResponse(**result)
