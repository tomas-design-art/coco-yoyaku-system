"""Web予約フォーム / Webチャット向けAPI（DB非永続セッション）"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, date, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.line_parser import parse_line_message
from app.database import get_db
from app.models.menu import Menu

from app.schemas.reservation import ReservationCreate
from app.services.reservation_service import create_reservation
from app.utils.datetime_jst import JST, now_jst
from app.api.line import (
    _resolve_menu,
    _menu_duration_bounds,
    _is_valid_duration_for_menu,
)
from app.services.slot_scorer import find_best_practitioner, score_candidates

router = APIRouter(prefix="/api", tags=["web_reserve"])


# DB保存しないWebチャット用の一時セッション
_WEB_CHAT_SESSIONS: dict[str, dict] = {}
_WEB_CHAT_TTL = timedelta(hours=2)


class WebReserveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., min_length=6, max_length=30)
    menu_id: int
    desired_datetime: str = Field(..., description="YYYY-MM-DDTHH:MM[:SS][+09:00]")
    duration: Optional[int] = Field(default=None, description="可変時間メニューの指定分")


class WebReserveSuccess(BaseModel):
    status: str
    reservation_id: int


class WebReserveConflict(BaseModel):
    status: str
    alternatives: list[str]


class WebChatSessionRequest(BaseModel):
    session_id: Optional[str] = None
    menu_id: Optional[int] = None
    duration: Optional[int] = None


class WebChatMessageRequest(BaseModel):
    session_id: str
    message: str


class WebChatResponse(BaseModel):
    session_id: str
    response: str
    actions: list[dict] = []
    reservation_created: None = None


def _prune_expired_sessions() -> None:
    now = now_jst()
    expired = [sid for sid, s in _WEB_CHAT_SESSIONS.items() if now - s.get("updated_at", now) > _WEB_CHAT_TTL]
    for sid in expired:
        _WEB_CHAT_SESSIONS.pop(sid, None)


def _touch_session(session_id: str) -> dict:
    _prune_expired_sessions()
    state = _WEB_CHAT_SESSIONS.get(session_id)
    if state is None:
        state = {
            "current_step": "waiting_menu",
            "draft": {},
            "messages": [{"role": "assistant", "content": "こんにちは。ご希望メニューを選んでくださいね。"}],
            "updated_at": now_jst(),
        }
        _WEB_CHAT_SESSIONS[session_id] = state
    state["updated_at"] = now_jst()
    return state


def _build_menu_actions(menus: list[Menu], max_items: int = 8) -> list[dict]:
    return [
        {"type": "menu_selection", "options": [m.name for m in menus[:max_items]]}
    ]


def _build_duration_actions(min_minutes: int, max_minutes: int) -> list[dict]:
    options = [f"{d}分" for d in range(min_minutes, max_minutes + 1, 10)]
    return [{"type": "duration_selection", "options": options[:13]}]


@router.post("/web_reserve", response_model=WebReserveSuccess | WebReserveConflict)
async def web_reserve(body: WebReserveRequest, db: AsyncSession = Depends(get_db)):
    menu = (await db.execute(select(Menu).where(Menu.id == body.menu_id, Menu.is_active == True))).scalar_one_or_none()
    if not menu:
        raise HTTPException(status_code=404, detail="メニューが見つかりません")

    try:
        desired_dt = datetime.fromisoformat(body.desired_datetime)
    except ValueError:
        raise HTTPException(status_code=400, detail="desired_datetime の形式が不正です")

    if desired_dt.tzinfo is None:
        desired_dt = desired_dt.replace(tzinfo=JST)
    else:
        desired_dt = desired_dt.astimezone(JST)

    duration = int(body.duration or menu.duration_minutes)
    if menu.is_duration_variable:
        if not _is_valid_duration_for_menu(menu, duration):
            min_minutes, max_minutes = _menu_duration_bounds(menu)
            raise HTTPException(
                status_code=400,
                detail=f"duration は {min_minutes}〜{max_minutes} 分（10分刻み）で指定してください",
            )
    else:
        duration = menu.duration_minutes

    target_date = desired_dt.date()
    target_time = desired_dt.time().replace(second=0, microsecond=0)

    practitioner, start_dt, end_dt, _, _ = await find_best_practitioner(db, target_date, target_time, duration)
    if not practitioner:
        scored = await score_candidates(db, target_date, target_time, duration, max_results=5)
        iso_alternatives = [
            datetime.combine(s.date, s.start_time, tzinfo=JST).isoformat()
            for s in scored
        ]
        return WebReserveConflict(status="conflict", alternatives=iso_alternatives)

    # 患者を検索 or 作成（電話番号 → LINE ID → 名前 のフォールバックマッチ）
    from app.services.patient_match import find_or_create_patient
    patient = await find_or_create_patient(db, name=body.name, phone=body.phone)

    reservation = await create_reservation(
        db,
        ReservationCreate(
            patient_id=patient.id,
            practitioner_id=practitioner.id,
            menu_id=menu.id,
            start_time=start_dt,
            end_time=end_dt,
            channel="CHATBOT",
            notes="Web予約フォームから登録",
        ),
    )
    return WebReserveSuccess(status="success", reservation_id=reservation["id"])


@router.post("/web_chatbot/session")
async def web_chatbot_session(body: WebChatSessionRequest, db: AsyncSession = Depends(get_db)):
    session_id = body.session_id or uuid.uuid4().hex
    state = _touch_session(session_id)

    if body.menu_id:
        menu = (await db.execute(select(Menu).where(Menu.id == body.menu_id, Menu.is_active == True))).scalar_one_or_none()
        if menu:
            duration = int(body.duration or menu.duration_minutes)
            if menu.is_duration_variable and not _is_valid_duration_for_menu(menu, duration):
                duration = menu.duration_minutes
            state["draft"].update({"menu_id": menu.id, "menu_name": menu.name, "duration_minutes": duration})
            state["current_step"] = "waiting_datetime"
            state["messages"] = [
                {"role": "assistant", "content": f"{menu.name}ですね。ご希望日時を教えてください。"}
            ]

    return {"session_id": session_id, "messages": state["messages"], "status": "active"}


@router.get("/web_chatbot/session/{session_id}")
async def get_web_chatbot_session(session_id: str):
    state = _touch_session(session_id)
    return {"session_id": session_id, "messages": state["messages"], "status": "active"}


@router.post("/web_chatbot/message", response_model=WebChatResponse)
async def web_chatbot_message(body: WebChatMessageRequest, db: AsyncSession = Depends(get_db)):
    state = _touch_session(body.session_id)
    text = body.message.strip()
    if not text:
        return WebChatResponse(session_id=body.session_id, response="メッセージをお願いします。", actions=[])

    state["messages"].append({"role": "user", "content": text})
    current_step = state.get("current_step", "waiting_menu")
    draft = state.get("draft", {})

    if current_step == "waiting_menu":
        menu = await _resolve_menu(db, text)
        if not menu:
            menus = (await db.execute(select(Menu).where(Menu.is_active == True).order_by(Menu.display_order))).scalars().all()
            response = "ご希望メニューを選んでくださいね。"
            actions = _build_menu_actions(menus)
            state["messages"].append({"role": "assistant", "content": response})
            return WebChatResponse(session_id=body.session_id, response=response, actions=actions)

        draft.update({"menu_id": menu.id, "menu_name": menu.name, "duration_minutes": menu.duration_minutes})
        state["draft"] = draft

        if menu.is_duration_variable:
            min_minutes, max_minutes = _menu_duration_bounds(menu)
            state["current_step"] = "waiting_time_duration"
            response = f"{menu.name}ですね。施術時間を{min_minutes}〜{max_minutes}分で選べます。"
            actions = _build_duration_actions(min_minutes, max_minutes)
            state["messages"].append({"role": "assistant", "content": response})
            return WebChatResponse(session_id=body.session_id, response=response, actions=actions)

        state["current_step"] = "waiting_datetime"
        response = f"{menu.name}ですね。ご希望日時を教えてください。"
        state["messages"].append({"role": "assistant", "content": response})
        return WebChatResponse(session_id=body.session_id, response=response, actions=[])

    if current_step == "waiting_time_duration":
        menu = await _resolve_menu(db, draft.get("menu_name"))
        if not menu:
            state["current_step"] = "waiting_menu"
            response = "メニューから選び直しをお願いします。"
            state["messages"].append({"role": "assistant", "content": response})
            return WebChatResponse(session_id=body.session_id, response=response, actions=[])

        from app.api.line import _extract_duration_minutes

        duration = _extract_duration_minutes(text)
        min_minutes, max_minutes = _menu_duration_bounds(menu)
        if duration is None or not _is_valid_duration_for_menu(menu, duration):
            response = f"{min_minutes}〜{max_minutes}分の10分刻みでお願いします。"
            actions = _build_duration_actions(min_minutes, max_minutes)
            state["messages"].append({"role": "assistant", "content": response})
            return WebChatResponse(session_id=body.session_id, response=response, actions=actions)

        draft["duration_minutes"] = duration
        state["draft"] = draft
        state["current_step"] = "waiting_datetime"
        response = "ありがとうございます。ご希望日時を教えてください。"
        state["messages"].append({"role": "assistant", "content": response})
        return WebChatResponse(session_id=body.session_id, response=response, actions=[])

    parsed = await parse_line_message(text, previous=draft)
    draft.update({"date": parsed.get("date"), "time": parsed.get("time")})
    state["draft"] = draft
    if not draft.get("date") or not draft.get("time"):
        response = "日時がまだ分からないため、例の形式でお願いします。例: 4/10 15:30"
        state["messages"].append({"role": "assistant", "content": response})
        return WebChatResponse(session_id=body.session_id, response=response, actions=[])

    target_date = date.fromisoformat(draft["date"])
    hh, mm = map(int, str(draft["time"]).split(":"))
    duration = int(draft.get("duration_minutes") or 60)
    practitioner, start_dt, end_dt, _, _ = await find_best_practitioner(db, target_date, time(hh, mm), duration)

    if practitioner:
        response = (
            f"{start_dt.strftime('%m/%d %H:%M')}でご案内できそうです。"
            "予約フォームでお名前と電話番号を入力して確定してください。"
        )
        state["messages"].append({"role": "assistant", "content": response})
        return WebChatResponse(session_id=body.session_id, response=response, actions=[])

    scored = await score_candidates(db, target_date, time(hh, mm), duration, max_results=3)
    options = [f"{s.date} {s.start_time.strftime('%H:%M')}" for s in scored]
    response = "そのお時間は埋まっていました。近い候補はこちらです。"
    actions = [{"type": "alternative_selection", "options": options}]
    state["messages"].append({"role": "assistant", "content": response})
    return WebChatResponse(session_id=body.session_id, response=response, actions=actions)
