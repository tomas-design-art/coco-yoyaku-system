import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sse", tags=["sse"])

# グローバルなイベントキュー（接続中のクライアントごと）
_clients: list[asyncio.Queue] = []


async def broadcast_event(event_type: str, data: dict):
    """全接続クライアントにSSEイベントを送信"""
    message = json.dumps(data, ensure_ascii=False, default=str)
    disconnected = []
    for i, queue in enumerate(_clients):
        try:
            queue.put_nowait({"event": event_type, "data": message})
        except Exception:
            disconnected.append(i)
    for i in reversed(disconnected):
        _clients.pop(i)


async def event_generator(request: Request) -> AsyncGenerator:
    queue: asyncio.Queue = asyncio.Queue()
    _clients.append(queue)
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield event
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": ""}
    finally:
        if queue in _clients:
            _clients.remove(queue)


@router.get("/events")
async def sse_events(request: Request):
    return EventSourceResponse(event_generator(request))
