"""シャドーモード解析ログ取得API"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.shadow_log import ShadowLog
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Any

router = APIRouter(prefix="/api/shadow-logs", tags=["shadow-logs"])


class ShadowLogResponse(BaseModel):
    id: int
    line_user_id: str
    display_name: Optional[str] = None
    raw_message: str
    has_reservation_intent: bool
    analysis_result: Optional[Any] = None
    notified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/", response_model=list[ShadowLogResponse])
async def list_shadow_logs(
    limit: int = Query(default=50, ge=1, le=200, description="取得件数（最大200）"),
    intent_only: bool = Query(default=False, description="予約意図ありのみ表示"),
    db: AsyncSession = Depends(get_db),
):
    """
    シャドーモードのAI解析ログを取得する。
    - limit: 直近N件（デフォルト50）
    - intent_only=true: 予約意図があると判定されたメッセージのみ絞り込み
    """
    query = select(ShadowLog).order_by(ShadowLog.created_at.desc()).limit(limit)
    if intent_only:
        query = query.where(ShadowLog.has_reservation_intent == True)

    result = await db.execute(query)
    return result.scalars().all()
