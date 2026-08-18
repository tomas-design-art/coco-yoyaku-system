"""LINE autopilot がシステムの確定値だけを根拠に答えられる質問への回答材料を集める。

ここで返すのは「DBが持っている事実」だけ。値が無ければ None を返し、担当者へ渡す。
料金・保険適用は menus.price / menu_price_tiers が未入力・可変のため回答対象にしない。
"""
from __future__ import annotations

import re
from datetime import date, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.menu import Menu
from app.models.practitioner import Practitioner
from app.services.business_hours import get_business_hours_for_date
from app.services.schedule_service import get_practitioner_working_hours, is_practitioner_working
from app.services.slot_scorer import build_same_day_candidates
from app.utils.datetime_jst import now_jst

PRICE_CATEGORY = "price"

_PRICE_PATTERN = re.compile(r"料金|値段|いくら|おいくら|費用|価格|会計|自費|保険.*(効|適用|使え)|何円")
_BUSINESS_HOURS_PATTERN = re.compile(r"営業|何時から|何時まで|開いて|やってま|やってる|休診|休み|定休|祝日|診療時間")
_AVAILABILITY_PATTERN = re.compile(r"空き|空いて|予約(?:は)?(?:できま|取れ|空)|埋まって")
_MENU_PATTERN = re.compile(r"メニュー|コース|何分|所要|施術時間|時間は選")
_PRACTITIONER_PATTERN = re.compile(r"出勤|いますか|いらっしゃ|担当|先生.*(休|出)|シフト")


def classify_question(text: str) -> str | None:
    """質問の種類を判定する（知識ではなく経路の振り分けのみ）。"""
    message = text or ""
    if _PRICE_PATTERN.search(message):
        return PRICE_CATEGORY
    if _PRACTITIONER_PATTERN.search(message):
        return "practitioner_schedule"
    if _AVAILABILITY_PATTERN.search(message):
        return "availability"
    if _BUSINESS_HOURS_PATTERN.search(message):
        return "business_hours"
    if _MENU_PATTERN.search(message):
        return "menu_info"
    return None


def _resolve_target_date(parsed: dict | None) -> date:
    raw = (parsed or {}).get("date")
    if raw:
        try:
            return date.fromisoformat(str(raw))
        except ValueError:
            pass
    return now_jst().date()


async def _find_mentioned_practitioner(db: AsyncSession, text: str) -> Practitioner | None:
    practitioners = (
        await db.execute(select(Practitioner).where(Practitioner.is_active == True))
    ).scalars().all()
    for practitioner in practitioners:
        name = (practitioner.name or "").strip()
        if not name:
            continue
        if name in text or name.split()[0] in text:
            return practitioner
    return None


async def _business_hours_facts(db: AsyncSession, target_date: date) -> dict:
    hours = await get_business_hours_for_date(db, target_date)
    return {
        "date": target_date.isoformat(),
        "is_open": hours.is_open,
        "open_time": hours.open_time if hours.is_open else None,
        "close_time": hours.close_time if hours.is_open else None,
        "label": hours.label,
    }


async def collect_question_facts(
    db: AsyncSession,
    text: str,
    parsed: dict | None = None,
) -> dict | None:
    """質問に対してシステムが根拠を持つ事実を返す。答えられなければ None。"""
    category = classify_question(text)
    if category is None:
        return None
    if category == PRICE_CATEGORY:
        return {"category": PRICE_CATEGORY}

    target_date = _resolve_target_date(parsed)

    if category == "business_hours":
        facts = await _business_hours_facts(db, target_date)
        return {"category": category, **facts}

    if category == "practitioner_schedule":
        practitioner = await _find_mentioned_practitioner(db, text)
        if not practitioner:
            return None
        working, _, _ = await is_practitioner_working(db, practitioner.id, target_date)
        start_time, end_time = (
            await get_practitioner_working_hours(db, practitioner.id, target_date)
            if working
            else (None, None)
        )
        return {
            "category": category,
            "date": target_date.isoformat(),
            "practitioner": practitioner.name,
            "is_working": working,
            "work_start": start_time,
            "work_end": end_time,
        }

    if category == "availability":
        hours = await get_business_hours_for_date(db, target_date)
        if not hours.is_open:
            return {"category": category, **await _business_hours_facts(db, target_date), "available_candidates": []}
        duration = int((parsed or {}).get("duration_minutes") or 60)
        candidates = await build_same_day_candidates(
            db,
            target_date,
            time(9, 0),
            duration,
            max_results=3,
        )
        return {
            "category": category,
            "date": target_date.isoformat(),
            "available_candidates": [candidate.to_dict() for candidate in candidates],
        }

    if category == "menu_info":
        menus = (
            await db.execute(
                select(Menu).where(Menu.is_active == True).order_by(Menu.display_order)
            )
        ).scalars().all()
        if not menus:
            return None
        return {
            "category": category,
            "menus": [
                {
                    "name": menu.name,
                    "duration_minutes": menu.duration_minutes,
                    "max_duration_minutes": menu.max_duration_minutes or menu.duration_minutes,
                    "is_duration_variable": bool(menu.is_duration_variable),
                }
                for menu in menus
            ],
            "duration_step_minutes": 10,
        }

    return None


async def next_open_dates(db: AsyncSession, start_date: date, limit: int = 3) -> list[str]:
    """営業している直近の日付を返す（別日提案の材料）。"""
    found: list[str] = []
    for offset in range(1, 15):
        target = start_date + timedelta(days=offset)
        hours = await get_business_hours_for_date(db, target)
        if hours.is_open:
            found.append(target.isoformat())
        if len(found) >= limit:
            break
    return found
