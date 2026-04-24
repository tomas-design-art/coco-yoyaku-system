"""LINE AI秘書の対話状態管理（DB永続化）。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.line_user_state import LineUserState
from app.utils.datetime_jst import now_jst


def _normalize_context(context_data: dict | None) -> dict:
    if isinstance(context_data, dict):
        return dict(context_data)
    return {}


async def _get_or_create_state(db: AsyncSession, line_user_id: str) -> LineUserState:
    result = await db.execute(
        select(LineUserState).where(LineUserState.line_user_id == line_user_id)
    )
    state = result.scalar_one_or_none()
    if state:
        return state

    state = LineUserState(
        line_user_id=line_user_id,
        current_step="idle",
        context_data={},
    )
    db.add(state)
    await db.flush()
    return state


async def create_pending_request(db: AsyncSession, payload: dict) -> str:
    line_user_id = payload.get("user_id")
    if not line_user_id:
        raise ValueError("user_id is required in payload")

    state = await _get_or_create_state(db, line_user_id)
    context = _normalize_context(state.context_data)
    requests = context.get("requests") if isinstance(context.get("requests"), dict) else {}

    rid = uuid.uuid4().hex[:12]
    now_iso = now_jst().isoformat()
    req_data = {
        "request_id": rid,
        "status": "pending_admin",
        "created_at": now_iso,
        "updated_at": now_iso,
        **payload,
    }
    requests[rid] = req_data

    context["requests"] = requests
    context["request_id"] = rid
    state.current_step = "adjusting"
    state.context_data = context
    await db.flush()
    return rid


async def _find_request_holder(
    db: AsyncSession,
    request_id: str,
    line_user_id: str | None = None,
) -> tuple[LineUserState, dict, dict, dict] | None:
    if line_user_id:
        result = await db.execute(
            select(LineUserState).where(LineUserState.line_user_id == line_user_id)
        )
        candidates = [result.scalar_one_or_none()]
    else:
        rows = await db.execute(select(LineUserState))
        candidates = list(rows.scalars().all())

    for state in candidates:
        if not state:
            continue
        context = _normalize_context(state.context_data)
        requests = context.get("requests") if isinstance(context.get("requests"), dict) else {}
        req = requests.get(request_id)
        if req:
            return state, context, requests, req
    return None


async def get_request(
    db: AsyncSession,
    request_id: str,
    line_user_id: str | None = None,
) -> dict | None:
    found = await _find_request_holder(db, request_id, line_user_id=line_user_id)
    if not found:
        return None
    return dict(found[3])


async def update_request(
    db: AsyncSession,
    request_id: str,
    line_user_id: str | None = None,
    **updates,
) -> dict | None:
    found = await _find_request_holder(db, request_id, line_user_id=line_user_id)
    if not found:
        return None

    state, context, requests, req = found
    req.update(updates)
    req["updated_at"] = now_jst().isoformat()
    requests[request_id] = req
    context["requests"] = requests
    state.context_data = context
    await db.flush()
    return dict(req)


async def get_user_mode(db: AsyncSession, line_user_id: str) -> str | None:
    result = await db.execute(
        select(LineUserState.current_step).where(LineUserState.line_user_id == line_user_id)
    )
    return result.scalar_one_or_none()


async def find_latest_pending_shadow_request(db: AsyncSession) -> tuple[str, str, dict] | None:
    """全ユーザーを走査して最新の pending_admin 状態のシャドー予約依頼を返す。
    戻り値: (line_user_id, request_id, request_payload) or None
    """
    rows = await db.execute(select(LineUserState))
    candidates: list[tuple[str, str, dict, str]] = []
    for state in rows.scalars().all():
        context = _normalize_context(state.context_data)
        requests = context.get("requests") if isinstance(context.get("requests"), dict) else {}
        for rid, req in requests.items():
            if not isinstance(req, dict):
                continue
            if req.get("status") != "pending_admin":
                continue
            if not req.get("shadow_mode"):
                continue
            updated = req.get("updated_at") or req.get("created_at") or ""
            candidates.append((state.line_user_id, rid, dict(req), str(updated)))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[3], reverse=True)
    uid, rid, req, _ = candidates[0]
    return uid, rid, req


async def get_user_state(db: AsyncSession, line_user_id: str) -> dict:
    state = await _get_or_create_state(db, line_user_id)
    context = _normalize_context(state.context_data)
    return {
        "line_user_id": line_user_id,
        "mode": state.current_step,
        "request_id": context.get("request_id"),
        "draft": context.get("draft") if isinstance(context.get("draft"), dict) else {},
        "context_data": context,
    }


async def merge_user_draft(
    db: AsyncSession,
    line_user_id: str,
    draft: dict,
    request_id: str | None = None,
) -> dict:
    state = await _get_or_create_state(db, line_user_id)
    context = _normalize_context(state.context_data)
    current_draft = context.get("draft") if isinstance(context.get("draft"), dict) else {}
    merged = {**current_draft, **{k: v for k, v in draft.items() if v not in (None, "")}}

    context["draft"] = merged
    if request_id is not None:
        context["request_id"] = request_id
    state.context_data = context

    if not state.current_step:
        state.current_step = "interviewing"
    await db.flush()
    return merged


async def clear_user_draft(db: AsyncSession, line_user_id: str) -> None:
    result = await db.execute(
        select(LineUserState).where(LineUserState.line_user_id == line_user_id)
    )
    state = result.scalar_one_or_none()
    if not state:
        return

    context = _normalize_context(state.context_data)
    context["draft"] = {}
    state.context_data = context
    await db.flush()


async def set_user_mode(
    db: AsyncSession,
    line_user_id: str,
    mode: str,
    request_id: str | None = None,
) -> None:
    state = await _get_or_create_state(db, line_user_id)
    context = _normalize_context(state.context_data)
    if request_id is not None:
        context["request_id"] = request_id
    else:
        context.pop("request_id", None)

    state.current_step = mode
    state.context_data = context
    await db.flush()
