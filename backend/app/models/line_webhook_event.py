"""LINE Webhook の受信記録。

再送・再起動で取りこぼさないために、署名検証の直後にここへ保存してから
200 を返し、実処理はバックエンドのスケジューラが DB を見て行う。
"""
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, JSON, Text
from sqlalchemy.sql import func

from app.database import Base


class LineWebhookEvent(Base):
    __tablename__ = "line_webhook_events"

    id = Column(Integer, primary_key=True, index=True)
    # LINE の webhookEventId。再送でも同じ値なので重複検知の鍵になる。
    event_id = Column(String(64), unique=True, nullable=False, index=True)
    line_user_id = Column(String(100), nullable=True, index=True)
    event_timestamp = Column(BigInteger, nullable=True)
    is_redelivery = Column(Boolean, nullable=False, default=False, server_default="false")
    payload = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
