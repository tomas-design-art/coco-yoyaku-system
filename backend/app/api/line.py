"""LINE Webhook & API（AI秘書: 第1段階）"""
import base64
from datetime import date, datetime, time, timedelta
import hashlib
import hmac
import inspect
import json
import logging
import re
from typing import Optional
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.line_parser import extract_full_name, parse_line_message
from app.config import settings
from app.database import get_db
from app.models.menu import Menu
from app.models.patient import Patient
from app.models.practitioner import Practitioner
from app.models.practitioner_unavailable_time import PractitionerUnavailableTime
from app.models.reservation import Reservation
from app.models.line_user_state import LineUserState
from app.models.setting import Setting
from app.schemas.reservation import ReservationCreate
from app.services.conflict_detector import check_conflict
from app.services.line_alerts import build_reservation_review_flex, push_admin_reservation_review
from app.services.line_composer import compose_reply
from app.services.line_debounce import clear_debounce, is_duplicate_message, merge_debounced_message
from app.services.slot_scorer import build_same_day_candidates, find_best_practitioner, score_candidates
from app.services.line_reply import push_message, reply_flex_message, reply_text_with_quick_reply, reply_to_line
from app.services.line_state import (
    clear_user_draft,
    create_pending_request,
    get_request,
    get_user_mode,
    get_user_state,
    merge_user_draft,
    set_user_mode,
    update_request,
)
from app.services.notification_service import create_notification
from app.services.patient_match import (
    create_new_patient,
    find_name_candidates,
    find_or_create_patient,
    find_unique_patient_by_phone,
    find_unique_patient_by_reading_and_birth_date,
    match_identity_token,
    normalize_phone,
)
from app.services.reservation_service import create_reservation, reschedule_reservation, transition_status
from app.services.schedule_service import is_practitioner_working
from app.services.shadow_service import handle_shadow_message
from app.utils.datetime_jst import JST, now_jst

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/line", tags=["line"])

AUTOPILOT_SETUP_KEYWORD = "#autopilot-setup"
_AUTOPILOT_SETUP_MODES = {
    "autopilot_setup_name_phone",
    "autopilot_setup_reading_birth",
    "autopilot_setup_confirm_new",
}


class LineMessageRequest(BaseModel):
    message: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None


def _verify_signature(body: bytes, signature: Optional[str]):
    if settings.line_channel_secret and settings.line_channel_secret != "xxx":
        if not signature:
            raise HTTPException(status_code=400, detail="署名がありません")
        hash_val = hmac.new(settings.line_channel_secret.encode(), body, hashlib.sha256).digest()
        expected = base64.b64encode(hash_val).decode()
        if expected != signature:
            raise HTTPException(status_code=403, detail="署名が不正です")


async def _get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    row = (await db.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
    return row.value if row else default


async def _get_line_display_name(user_id: str) -> str | None:
    if not settings.line_channel_access_token or settings.line_channel_access_token == "xxx":
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.line.me/v2/bot/profile/{user_id}",
                headers={"Authorization": f"Bearer {settings.line_channel_access_token}"},
                timeout=8,
            )
            if resp.status_code == 200:
                return resp.json().get("displayName")
    except Exception as e:
        logger.warning("LINE profile fetch failed: %s", e)
    return None


def _line_mirror_is_configured() -> bool:
    return bool(
        settings.line_mirror_enabled
        and settings.line_mirror_url
        and settings.line_mirror_shared_secret
    )


async def _forward_line_webhook_to_mirror(payload: dict) -> None:
    """本番LINE Webhookイベントをstagingへ複製転送する。

    転送失敗は本番Webhook処理へ影響させない。
    """
    if not _line_mirror_is_configured():
        return

    try:
        mirror_payload = json.loads(json.dumps(payload))
        events = mirror_payload.get("events", [])
        if not isinstance(events, list) or not events:
            return

        for event in events:
            if not isinstance(event, dict):
                continue
            source = event.get("source") if isinstance(event.get("source"), dict) else {}
            user_id = source.get("userId")
            display_name = await _get_line_display_name(user_id) if user_id else None
            event["_mirror"] = {
                "displayName": display_name,
                "sourceEnvironment": settings.environment,
                "label": settings.line_mirror_label,
                "mirroredAt": now_jst().isoformat(),
            }

        mirror_payload["mirror"] = {
            "sourceEnvironment": settings.environment,
            "label": settings.line_mirror_label,
            "mirroredAt": now_jst().isoformat(),
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.line_mirror_url,
                json=mirror_payload,
                headers={"X-Line-Mirror-Secret": settings.line_mirror_shared_secret},
                timeout=settings.line_mirror_timeout_seconds,
            )
            if resp.status_code >= 300:
                logger.warning("LINE mirror forward failed: %s %s", resp.status_code, resp.text[:300])
    except Exception as e:
        logger.warning("LINE mirror forward error: %s", e)


def _mirror_display_name(event: dict, label: str) -> str:
    mirror = event.get("_mirror") if isinstance(event.get("_mirror"), dict) else {}
    source = event.get("source") if isinstance(event.get("source"), dict) else {}
    user_id = source.get("userId") or "unknown"
    base_name = mirror.get("displayName") or user_id[:12]
    return f"[{label}] {base_name}"


def _build_missing_info_message(missing: list[str]) -> str:
    jp_map = {
        "customer_name": "お名前",
        "date": "ご希望日",
        "time": "ご希望時間",
        "menu_name": "ご希望メニュー",
    }
    labels = [jp_map.get(k, k) for k in missing]
    joined = "】と【".join(labels)
    return (
        "ご連絡ありがとうございます。予約枠を確認いたしますので、"
        f"恐れ入りますが【{joined}】を教えていただけますでしょうか？"
    )


def _format_usual_shortcut_text(menu_name: str, duration_minutes: int, practitioner_name: str | None = None) -> str:
    if practitioner_name:
        return f"⭐️いつもの（{menu_name} {duration_minutes}分・担当: {practitioner_name}）"
    return f"⭐️いつもの（{menu_name} {duration_minutes}分）"


def _build_duration_quick_reply_items(min_minutes: int, max_minutes: int, max_items: int = 13) -> list[dict]:
    items: list[dict] = []
    for d in range(min_minutes, max_minutes + 1, 10):
        if len(items) >= max_items:
            break
        label = f"{d}分"
        items.append(
            {
                "type": "action",
                "action": {
                    "type": "message",
                    "label": label,
                    "text": label,
                },
            }
        )
    return items


def _build_yes_no_new_quick_reply_items() -> list[dict]:
    return [
        {
            "type": "action",
            "action": {"type": "message", "label": "はい", "text": "はい"},
        },
        {
            "type": "action",
            "action": {"type": "message", "label": "いいえ", "text": "いいえ"},
        },
        {
            "type": "action",
            "action": {"type": "message", "label": "新規登録", "text": "新規登録"},
        },
    ]


def _extract_duration_minutes(text: str) -> int | None:
    m = re.search(r"(\d{2,3})\s*分", text)
    if m:
        return int(m.group(1))
    if text.isdigit():
        return int(text)
    return None


async def _get_latest_reservation_for_line_user(db: AsyncSession, line_user_id: str) -> dict | None:
    result = await db.execute(
        select(Reservation, Menu)
        .join(Patient, Reservation.patient_id == Patient.id)
        .outerjoin(Menu, Reservation.menu_id == Menu.id)
        .where(Patient.line_id == line_user_id, Reservation.status != "CANCELLED")
        .order_by(Reservation.created_at.desc())
        .limit(1)
    )
    row = result.first() if hasattr(result, "first") else None
    if inspect.isawaitable(row):
        row = await row
    if not row:
        return None

    try:
        reservation, menu = row
    except Exception:
        return None

    if not getattr(reservation, "start_time", None) or not getattr(reservation, "end_time", None):
        return None
    duration = int((reservation.end_time - reservation.start_time).total_seconds() // 60)
    return {
        "menu_id": reservation.menu_id,
        "menu_name": menu.name if menu else "前回メニュー",
        "duration_minutes": duration,
    }


async def _get_patient_default_preset(db: AsyncSession, patient: Patient | None) -> dict | None:
    """患者のデフォルト設定からいつものプリセットを返す。
    default_menu_id が設定されていれば返す。preferred_practitioner_id は任意。
    """
    default_menu_id = getattr(patient, "default_menu_id", None) if patient else None
    if not patient or not default_menu_id:
        return None
    menu = (
        await db.execute(select(Menu).where(Menu.id == default_menu_id, Menu.is_active == True))
    ).scalar_one_or_none()
    if not menu:
        return None
    duration = getattr(patient, "default_duration", None) or menu.duration_minutes
    practitioner_id = None
    practitioner_name = None
    preferred_practitioner_id = getattr(patient, "preferred_practitioner_id", None)
    if preferred_practitioner_id:
        practitioner = (
            await db.execute(select(Practitioner).where(Practitioner.id == preferred_practitioner_id))
        ).scalar_one_or_none()
        if practitioner:
            practitioner_id = practitioner.id
            practitioner_name = practitioner.name
    return {
        "menu_id": menu.id,
        "menu_name": menu.name,
        "duration_minutes": duration,
        "practitioner_id": practitioner_id,
        "practitioner_name": practitioner_name,
    }


async def _build_menu_quick_reply_items(
    db: AsyncSession,
    line_user_id: str | None = None,
    max_items: int = 6,
    patient: Patient | None = None,
) -> list[dict]:
    defaults = ["初診", "保険診療", "骨盤矯正", "全身調整"]
    menu_names: list[str] = []
    items: list[dict] = []

    # 患者デフォルト設定（担当者あり）を優先、なければ直近予約履歴を使う
    preset = await _get_patient_default_preset(db, patient)
    if preset:
        quick_text = _format_usual_shortcut_text(
            preset["menu_name"], preset["duration_minutes"], preset["practitioner_name"]
        )
        items.append(
            {
                "type": "action",
                "action": {
                    "type": "message",
                    "label": "⭐️いつもの",
                    "text": quick_text,
                },
            }
        )
    elif line_user_id:
        latest = await _get_latest_reservation_for_line_user(db, line_user_id)
        if latest:
            quick_text = _format_usual_shortcut_text(latest["menu_name"], latest["duration_minutes"])
            items.append(
                {
                    "type": "action",
                    "action": {
                        "type": "message",
                        "label": "⭐️いつもの",
                        "text": quick_text,
                    },
                }
            )

    menus = (await db.execute(select(Menu).where(Menu.is_active == True).order_by(Menu.display_order))).scalars().all()
    for m in menus:
        if m.name and m.name not in menu_names:
            menu_names.append(m.name)
        if len(menu_names) >= max_items:
            break
    if not menu_names:
        menu_names = defaults

    for name in menu_names[:max_items]:
        items.append(
            {
                "type": "action",
                "action": {
                    "type": "message",
                    "label": name[:20],
                    "text": name,
                },
            }
        )
    return items


async def _resolve_menu(db: AsyncSession, menu_name: str | None) -> Menu | None:
    if not menu_name:
        return None
    exact = (
        await db.execute(select(Menu).where(Menu.is_active == True, Menu.name == menu_name).limit(1))
    ).scalar_one_or_none()
    if exact:
        return exact
    menus = (await db.execute(select(Menu).where(Menu.is_active == True))).scalars().all()
    for m in menus:
        if m.name in menu_name or menu_name in m.name:
            return m
    return None


def _menu_duration_bounds(menu: Menu) -> tuple[int, int]:
    min_minutes = int(menu.duration_minutes)
    max_minutes = int(menu.max_duration_minutes or menu.duration_minutes)
    if max_minutes < min_minutes:
        max_minutes = min_minutes
    return min_minutes, max_minutes


def _is_valid_duration_for_menu(menu: Menu, duration: int) -> bool:
    min_minutes, max_minutes = _menu_duration_bounds(menu)
    return min_minutes <= duration <= max_minutes and (duration - min_minutes) % 10 == 0


async def _find_available_practitioner(
    db: AsyncSession,
    target_date: date,
    start_time: time,
    duration_minutes: int,
) -> tuple[Practitioner | None, datetime, datetime]:
    start_dt = datetime.combine(target_date, start_time, tzinfo=JST)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    practitioners = (
        await db.execute(select(Practitioner).where(Practitioner.is_active == True).order_by(Practitioner.display_order))
    ).scalars().all()

    for p in practitioners:
        working, _, _ = await is_practitioner_working(db, p.id, target_date)
        if not working:
            continue

        # 時間帯休みチェック
        uts = (
            await db.execute(
                select(PractitionerUnavailableTime).where(
                    and_(
                        PractitionerUnavailableTime.practitioner_id == p.id,
                        PractitionerUnavailableTime.date == target_date,
                    )
                )
            )
        ).scalars().all()
        blocked = False
        s_min = start_dt.hour * 60 + start_dt.minute
        e_min = end_dt.hour * 60 + end_dt.minute
        for ut in uts:
            sh, sm = map(int, ut.start_time.split(":"))
            eh, em = map(int, ut.end_time.split(":"))
            ut_s = sh * 60 + sm
            ut_e = eh * 60 + em
            if s_min < ut_e and e_min > ut_s:
                blocked = True
                break
        if blocked:
            continue

        conflicts = await check_conflict(db, p.id, start_dt, end_dt)
        if not conflicts:
            return p, start_dt, end_dt

    return None, start_dt, end_dt


async def _suggest_alternatives(
    db: AsyncSession,
    base_date: date,
    base_time: time,
    duration_minutes: int,
    max_items: int = 3,
) -> list[dict]:
    alternatives: list[dict] = []
    slot_min = 30
    base_minutes = base_time.hour * 60 + base_time.minute

    for day_offset in range(0, 4):
        d = base_date + timedelta(days=day_offset)
        for delta in [0, -60, 60, -120, 120, -180, 180]:
            mins = base_minutes + delta
            if mins < 9 * 60 or mins > 19 * 60:
                continue
            t = time(mins // 60, mins % 60)
            if (mins % slot_min) != 0:
                continue
            p, s, e = await _find_available_practitioner(db, d, t, duration_minutes)
            if p:
                label = f"{d.isoformat()} {s.strftime('%H:%M')}〜{e.strftime('%H:%M')}（{p.name}）"
                if not any(a["label"] == label for a in alternatives):
                    alternatives.append(
                        {
                            "date": d.isoformat(),
                            "start": s.strftime("%H:%M"),
                            "end": e.strftime("%H:%M"),
                            "practitioner_id": p.id,
                            "practitioner_name": p.name,
                            "label": label,
                        }
                    )
            if len(alternatives) >= max_items:
                return alternatives
    return alternatives


async def _find_or_create_line_patient(db: AsyncSession, user_id: str, name: str | None) -> Patient:
    return await find_or_create_patient(db, name=name, line_id=user_id)


async def _get_or_create_shadow_timetable_patient(db: AsyncSession, user_id: str) -> Patient:
    """シャドーモードのタイムテーブル登録専用ダミー患者を返す。

    Bot通知や解析には実文面を残すが、stagingの予約ボードには実患者名やline_idを残さない。
    同じLINEユーザーには同じ「シャドーN」を再利用する。
    """
    state_result = await db.execute(
        select(LineUserState).where(LineUserState.line_user_id == user_id)
    )
    state = state_result.scalar_one_or_none()
    if not state:
        state = LineUserState(line_user_id=user_id, current_step="idle", context_data={})
        db.add(state)
        await db.flush()

    context = dict(state.context_data) if isinstance(state.context_data, dict) else {}
    shadow_patient_id = context.get("shadow_patient_id")
    if shadow_patient_id:
        patient = await db.get(Patient, int(shadow_patient_id))
        if patient and str(patient.name or "").startswith("シャドー"):
            return patient

    existing_result = await db.execute(select(Patient).where(Patient.name.like("シャドー%")))
    max_number = 0
    for patient in existing_result.scalars().all():
        match = re.fullmatch(r"シャドー(\d+)", patient.name or "")
        if match:
            max_number = max(max_number, int(match.group(1)))

    alias_name = f"シャドー{max_number + 1}"
    patient = await create_new_patient(
        db,
        name=alias_name,
        line_id=None,
        notes="LINE shadow timetable dummy patient",
    )
    context["shadow_patient_id"] = patient.id
    context["shadow_patient_name"] = alias_name
    state.context_data = context
    await db.flush()
    return patient


async def _find_line_patient(db: AsyncSession, user_id: str) -> Patient | None:
    return (
        await db.execute(select(Patient).where(Patient.line_id == user_id).limit(1))
    ).scalar_one_or_none()


async def _register_line_patient(db: AsyncSession, user_id: str, full_name: str) -> Patient:
    return await find_or_create_patient(db, name=full_name, line_id=user_id)


async def _register_line_patient_as_new(db: AsyncSession, user_id: str, full_name: str) -> Patient:
    return await create_new_patient(db, name=full_name, line_id=user_id)


def _autopilot_is_globally_enabled() -> bool:
    return getattr(settings, "line_autopilot_enabled", False) is True


def _extract_phone_from_setup_message(text: str) -> str | None:
    match = re.search(r"(?:\+81|81|0)[0-9０-９－ー -]{8,16}", text or "")
    return normalize_phone(match.group(0)) if match else None


def _extract_setup_name_and_phone(text: str, profile_name: str | None) -> tuple[str | None, str | None]:
    phone = _extract_phone_from_setup_message(text)
    name_source = re.sub(r"(?:\+81|81|0)[0-9０-９－ー -]{8,16}", "", text or "").strip()
    name = extract_full_name(name_source, profile_name=profile_name)
    return name, phone


def _extract_reading_and_birth_date(text: str) -> tuple[str | None, date | None]:
    match = re.search(r"\b(19\d{2}|20\d{2})[/-](\d{1,2})[/-](\d{1,2})\b", text or "")
    if not match:
        return None, None
    try:
        birth_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None, None
    reading = (text[:match.start()] + text[match.end():]).strip(" \u3000、,，")
    return reading or None, birth_date


def _has_explicit_new_registration_intent(text: str) -> bool:
    normalized = (text or "").replace(" ", "").replace("\u3000", "")
    return any(phrase in normalized for phrase in ("新規登録", "新規利用", "初めての利用", "初めて利用", "初診です"))


async def _activate_autopilot_patient(db: AsyncSession, patient: Patient, user_id: str) -> bool:
    """LINE ID を他患者へ上書きせず、setup済み患者だけを有効化する。"""
    linked_patient = await _find_line_patient(db, user_id)
    if linked_patient and linked_patient.id != patient.id:
        return False
    patient.line_id = user_id
    patient.line_autopilot_enabled = True
    await db.flush()
    return True


async def _complete_autopilot_setup(
    db: AsyncSession,
    user_id: str,
    reply_token: str | None,
    patient: Patient,
) -> None:
    if not await _activate_autopilot_patient(db, patient, user_id):
        await set_user_mode(db, user_id, "manual")
        if reply_token:
            await reply_to_line(reply_token, "LINE連携の確認ができないため、担当者が対応します。")
        return
    await clear_user_draft(db, user_id)
    await set_user_mode(db, user_id, "idle")
    if reply_token:
        await reply_to_line(
            reply_token,
            "LINE連携が完了しました。以後は予約・変更・キャンセルをLINEで承ります。",
        )


async def _find_single_upcoming_reservation(db: AsyncSession, patient_id: int) -> Reservation | None:
    reservations = (
        await db.execute(
            select(Reservation)
            .where(
                Reservation.patient_id == patient_id,
                Reservation.status == "CONFIRMED",
                Reservation.start_time >= now_jst(),
            )
            .order_by(Reservation.start_time)
            .limit(2)
        )
    ).scalars().all()
    return reservations[0] if len(reservations) == 1 else None


def _requires_manual_autopilot_handling(text: str) -> bool:
    return any(word in (text or "") for word in ("遅刻", "遅れ", "相談", "問合せ", "問い合わせ"))


def _is_booking_or_change_menu_trigger(text: str) -> bool:
    return (text or "").strip().replace("／", "/") in {"予約/変更", "予約", "変更"}


def _looks_like_autopilot_booking_message(text: str) -> bool:
    normalized = (text or "").strip()
    return any(
        token in normalized
        for token in (
            "予約", "よやく", "空き", "あき", "取りたい", "お願い", "いつもの",
            "今日", "明日", "明後日", "午前", "午後", "夕方", "夜", "朝", "曜日",
            "キャンセル", "取消", "変更", "変え", "ずら", "リスケ",
            "cancel", "reschedule", "change", "appointment",
        )
    )


def _normalize_confirmation_text(text: str) -> str:
    return re.sub(r"[\s\u3000,，!！?？。､、…]+", "", (text or "").lower())


# 否定を先に判定するので「いいえ」が肯定の「いい」に誤爆しない。
_NEGATIVE_MARKERS = (
    "いいえ", "いや", "やだ", "やめ", "だめ", "ちがう", "違う", "結構", "けっこう",
    "取りやめ", "とりやめ", "no", "nope",
)
_AFFIRMATIVE_MARKERS = (
    "はい", "うん", "ええ", "いいよ", "いいですよ", "いいです", "それでいい", "それで",
    "おねがい", "お願い", "だいじょうぶ", "大丈夫", "了解", "りょうかい", "りょ",
    "よろしく", "オッケー", "おっけー", "おけ", "ok", "okay", "yes", "yeah", "yep",
    "sure", "please", "네", "예", "응", "好",
)


def _is_negative(text: str) -> bool:
    t = (text or "").lower()
    return any(marker in t for marker in _NEGATIVE_MARKERS)


def _is_affirmative(text: str) -> bool:
    if _is_negative(text):
        return False
    t = (text or "").lower()
    return any(marker in t for marker in _AFFIRMATIVE_MARKERS)


def _extract_alternative_choice(text: str, count: int) -> int | None:
    normalized = _normalize_confirmation_text(text).translate(
        str.maketrans("０１２３４５６７８９", "0123456789")
    )
    match = re.search(r"(?<!\d)([1-9])(?!\d)", normalized)
    if not match:
        return None
    choice = int(match.group(1))
    return choice if 1 <= choice <= count else None


def _has_cancellation_intent(text: str) -> bool:
    return bool(re.search(r"キャンセル|取り消|取消|やめたい|cancel|annul|cancelar|취소", text or "", re.IGNORECASE))


def _has_change_intent(text: str) -> bool:
    return bool(re.search(r"変更|変え|ずら|リスケ|reschedule|change|move|改期|更改|변경", text or "", re.IGNORECASE))


def _format_usual_confirmation(preset: dict) -> str:
    practitioner = f"・担当: {preset['practitioner_name']}" if preset.get("practitioner_name") else ""
    return f"いつもの{preset['menu_name']} {preset['duration_minutes']}分{practitioner}でよろしいですか？\nはい / いいえ"


async def _complete_autopilot_reschedule(
    db: AsyncSession,
    *,
    reservation: Reservation,
    desired_date: str,
    desired_time: str,
    user_id: str,
    reply_token: str | None,
) -> bool:
    """変更候補を提示し、患者の明示確認を待つ。"""
    try:
        target_date = date.fromisoformat(desired_date)
        target_time = time.fromisoformat(desired_time)
        duration = int((reservation.end_time - reservation.start_time).total_seconds() // 60)
        practitioner, start_dt, end_dt, _, _ = await find_best_practitioner(
            db, target_date, target_time, duration
        )
        if not practitioner:
            raise HTTPException(status_code=409, detail="変更先に空き枠がありません")
    except (HTTPException, ValueError):
        await set_user_mode(db, user_id, "autopilot_change_datetime")
        if reply_token:
            await reply_to_line(reply_token, "ご希望の枠はご案内できませんでした。別のご希望日時を教えてください。\n例: 明日の午後3時")
        return False

    await merge_user_draft(
        db,
        user_id,
        {
            "autopilot_change_reservation_id": reservation.id,
            "autopilot_change_start_time_iso": start_dt.isoformat(),
            "autopilot_change_end_time_iso": end_dt.isoformat(),
            "autopilot_change_practitioner_id": practitioner.id,
            "autopilot_change_practitioner_name": practitioner.name,
        },
    )
    await set_user_mode(db, user_id, "autopilot_change_confirm")
    if reply_token:
        await reply_to_line(
            reply_token,
            "変更後の候補をご確認ください。\n"
            + _format_autopilot_slot_confirmation(start_dt, end_dt, practitioner.name),
        )
    return True


async def _handle_autopilot_setup_message(
    db: AsyncSession,
    *,
    user_id: str,
    text: str,
    reply_token: str | None,
    display_name: str | None,
    state: dict,
) -> bool:
    """合言葉で開始する、氏名単独照合を行わないLINE連携セットアップ。"""
    mode = state.get("mode")
    draft = state.get("draft") or {}

    if text.strip() == AUTOPILOT_SETUP_KEYWORD:
        await clear_user_draft(db, user_id)
        await set_user_mode(db, user_id, "autopilot_setup_name_phone")
        if reply_token:
            await reply_to_line(
                reply_token,
                "ご利用ありがとうございます。\n"
                "予約システムに登録されているCOCO整骨院でのご利用履歴と照合します。\n"
                "お名前をフルネームで入力し、登録済みの電話番号を続けて入力してください。\n"
                "例: 山田 太郎 090-1234-5678",
            )
        return True

    if mode not in _AUTOPILOT_SETUP_MODES:
        return False

    if mode == "autopilot_setup_name_phone":
        name, phone = _extract_setup_name_and_phone(text, display_name)
        if _has_explicit_new_registration_intent(text) and name:
            await merge_user_draft(db, user_id, {"setup_name": name, "setup_phone": phone})
            await set_user_mode(db, user_id, "autopilot_setup_confirm_new")
            if reply_token:
                await reply_to_line(reply_token, "新規登録として進めます。よろしければ「はい」と返信してください。")
            return True
        if not name or not phone:
            if reply_token:
                await reply_to_line(reply_token, "お名前をフルネームで入力し、登録済みの電話番号を続けて入力してください。\n例: 山田 太郎 090-1234-5678")
            return True

        await merge_user_draft(db, user_id, {"setup_name": name, "setup_phone": phone})
        patient = await find_unique_patient_by_phone(db, phone)
        if patient:
            await _complete_autopilot_setup(db, user_id, reply_token, patient)
            return True

        await set_user_mode(db, user_id, "autopilot_setup_reading_birth")
        if reply_token:
            await reply_to_line(
                reply_token,
                "電話番号では照合できませんでした。\n"
                "お名前の読み仮名と生年月日を入力してください。\n"
                "例: やまだ たろう 1990-04-01",
            )
        return True

    if mode == "autopilot_setup_reading_birth":
        reading, birth_date = _extract_reading_and_birth_date(text)
        if not reading or not birth_date:
            if reply_token:
                await reply_to_line(reply_token, "お名前の読み仮名と生年月日を入力してください。\n例: やまだ たろう 1990-04-01")
            return True
        await merge_user_draft(db, user_id, {"setup_reading": reading, "setup_birth_date": birth_date.isoformat()})
        patient = await find_unique_patient_by_reading_and_birth_date(db, reading, birth_date)
        if patient:
            await _complete_autopilot_setup(db, user_id, reply_token, patient)
            return True

        await set_user_mode(db, user_id, "autopilot_setup_confirm_new")
        if reply_token:
            await reply_to_line(reply_token, "ご利用履歴を確認できませんでした。新規登録として進めます。よろしければ「はい」と返信してください。")
        return True

    if mode == "autopilot_setup_confirm_new":
        if text.strip() not in {"はい", "新規登録", "新規利用", "初めての利用"}:
            if reply_token:
                await reply_to_line(reply_token, "新規登録として進める場合は「はい」と返信してください。")
            return True
        name = draft.get("setup_name")
        if not name:
            await set_user_mode(db, user_id, "autopilot_setup_name_phone")
            if reply_token:
                await reply_to_line(reply_token, "新規登録のため、お名前をフルネームで入力し、電話番号を続けて入力してください。")
            return True
        birth_raw = draft.get("setup_birth_date")
        birth_date = date.fromisoformat(birth_raw) if birth_raw else None
        patient = await create_new_patient(
            db,
            name=name,
            phone=draft.get("setup_phone"),
            reading=draft.get("setup_reading"),
            birth_date=birth_date,
        )
        await _complete_autopilot_setup(db, user_id, reply_token, patient)
        return True

    return False


async def _generate_patient_number_line(db: AsyncSession) -> str:
    max_num = (
        await db.execute(
            select(func.max(Patient.patient_number))
            .where(Patient.patient_number.op("~")(r"^P\d+$"))
        )
    ).scalar()
    next_val = int(max_num[1:]) + 1 if max_num else 1
    return f"P{next_val:06d}"


def _compose_alternatives_text(alternatives: list[dict], vague: bool = False) -> str:
    if not alternatives:
        return (
            "申し訳ありません、ご希望に近い空き枠が見つかりませんでした。\n"
            "別の日時をお知らせいただければ、あらためてお探しします。\n"
            "例:「明日の夕方は？」「金曜の午前中で」"
        )
    header = (
        "空いているお時間をご案内します。"
        if vague
        else "ご希望の時間は満席でしたので、空いているお時間をご案内します。"
    )
    lines = [header]
    for i, a in enumerate(alternatives, start=1):
        lines.append(f"{i}. {a['label']}")
    lines.append("ご希望の番号を返信してください（例: 2）。")
    lines.append(
        "上記にご希望に合うものがなければ、遠慮なく別の日時をお知らせください。"
        "（例:「なら明日の午後は？」「金曜の夕方でお願い」）あらためてお探しします。"
    )
    return "\n".join(lines)


def _format_autopilot_slot_confirmation(start_dt: datetime, end_dt: datetime, practitioner_name: str, note: str | None = None) -> str:
    prefix = f"{note}\n" if note else ""
    return (
        f"{prefix}{_format_date_with_weekday_jp(start_dt.date())} {start_dt.strftime('%H:%M')}〜{end_dt.strftime('%H:%M')}"
        f"（担当: {practitioner_name}）でよろしいでしょうか？\nはい / いいえ"
    )


def _has_vague_time_period(text: str) -> bool:
    return bool(re.search(r"午前(?:中)?|午後|夕方|夜|晩|朝|morning|afternoon|evening|night", text or "", re.IGNORECASE))


def _vague_time_window(text: str) -> tuple[int, int] | None:
    """曖昧な時間帯表現から (開始分, 終了分) を返す。無ければ None。"""
    t = text or ""
    if re.search(r"午前|朝|morning", t, re.IGNORECASE):
        return (0, 12 * 60)
    if re.search(r"夕方|evening", t, re.IGNORECASE):
        return (16 * 60, 24 * 60)
    if re.search(r"夜|晩|night", t, re.IGNORECASE):
        return (18 * 60, 24 * 60)
    if re.search(r"昼", t):
        return (11 * 60, 14 * 60)
    if re.search(r"午後|afternoon", t, re.IGNORECASE):
        return (12 * 60, 24 * 60)
    return None


async def _extract_requested_practitioner(db: AsyncSession, text: str) -> Practitioner | None:
    """本文から明示的な担当指名（例: 上田さんで / 担当は時田）を抽出する。"""
    if not text:
        return None
    practitioners = (
        await db.execute(select(Practitioner).where(Practitioner.is_active == True))
    ).scalars().all()
    for p in practitioners:
        if not p.name:
            continue
        surname = p.name.split()[0]
        # 指名の合図（さん/先生/で/希望/指名/がいい/にして/でお願い、または「担当」前置）を伴う場合のみ採用
        pattern = rf"(?:担当[はを:：]?\s*)?{re.escape(surname)}\s*(?:さん|先生)?\s*(?:で|に|希望|指名|がいい|がいいです|にして|でお願い|でお願いします|でお願いしたい)"
        if re.search(pattern, text):
            return p
    return None


def _format_date_with_weekday_jp(d: date) -> str:
    weekday = ["月", "火", "水", "木", "金", "土", "日"][d.weekday()]
    return f"{d.month}/{d.day}({weekday})"


async def _handle_text_message(event: dict, db: AsyncSession):
    text = event.get("message", {}).get("text", "")
    source = event.get("source", {})
    user_id = source.get("userId", "")
    reply_token = event.get("replyToken")

    if not user_id:
        return

    user_state: dict | None = None
    display_name: str | None = None
    line_patient: Patient | None = None
    is_autopilot_patient = False
    if _autopilot_is_globally_enabled():
        user_state = await get_user_state(db, user_id)
        display_name = await _get_line_display_name(user_id)
        if await _handle_autopilot_setup_message(
            db,
            user_id=user_id,
            text=text,
            reply_token=reply_token,
            display_name=display_name,
            state=user_state,
        ):
            return
        line_patient = await _find_line_patient(db, user_id)
        is_autopilot_patient = bool(line_patient and line_patient.line_autopilot_enabled)

    # LINE の再送 webhook は予約会話を二重に進めてしまうため、対象患者だけで捨てる。
    if is_autopilot_patient and is_duplicate_message(user_id, text):
        logger.info("Autopilot: duplicate message skipped (user=%s)", user_id[:12])
        return
    if is_autopilot_patient and not _is_booking_or_change_menu_trigger(text):
        text = merge_debounced_message(user_id, text)

    # ── 管理者コマンド: Botくん1号 DM から「押さえる」「確定」で最新 pending を承認 ──
    admin_dev_uid = settings.admin_line_developer_user_id
    if admin_dev_uid and user_id == admin_dev_uid:
        if await _handle_admin_text_command(db, text, reply_token):
            return

    # ── シャドーモード: 既存フロー完全バイパス ──
    if settings.shadow_mode and not is_autopilot_patient:
        if display_name is None:
            display_name = await _get_line_display_name(user_id)
        await handle_shadow_message(
            db,
            user_id=user_id,
            text=text,
            display_name=display_name,
        )
        # 患者には一切返信しない（HTTP 200 のみ）
        return

    # リッチメニューの「予約/変更」は具体的な変更依頼ではない。
    # 過去にmanualへ退避した対象者も、ここから予約会話を再開できる。
    if is_autopilot_patient and _is_booking_or_change_menu_trigger(text):
        await clear_user_draft(db, user_id)
        await set_user_mode(db, user_id, "waiting_menu")
        if reply_token:
            quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
            await reply_text_with_quick_reply(
                reply_token,
                "ご希望メニューを選んでください。",
                quick_items,
            )
        return

    # 管理者が「自分で返信」を選択したユーザーは自動返信停止
    if await get_user_mode(db, user_id) == "manual":
        if is_autopilot_patient and _looks_like_autopilot_booking_message(text):
            clear_debounce(user_id)
            text = event.get("message", {}).get("text", "")
            await clear_user_draft(db, user_id)
            await set_user_mode(db, user_id, "idle")
            user_state = {**user_state, "mode": "idle", "draft": {}, "request_id": None}
        else:
            await create_notification(db, "line_manual_mode", f"手動対応中の患者から新着メッセージ: {line_patient.name if line_patient else user_id}様")
            if reply_token:
                await reply_to_line(reply_token, "担当者が内容を確認中です。しばらくお待ちください。")
            return

    if user_state is None:
        user_state = await get_user_state(db, user_id)
    if display_name is None:
        display_name = await _get_line_display_name(user_id)
    if line_patient is None:
        line_patient = await _find_line_patient(db, user_id)

    prev_draft = user_state.get("draft") or {}
    current_mode = user_state.get("mode")
    latest_reservation = await _get_latest_reservation_for_line_user(db, user_id)
    merged: dict | None = None
    parsed_intent: dict | None = None
    if is_autopilot_patient:
        parsed_intent = await parse_line_message(text, profile_name=display_name, previous=prev_draft)
        if parsed_intent.get("needs_human"):
            await set_user_mode(db, user_id, "manual")
            await create_notification(db, "line_manual_mode", f"LINE手動対応: {line_patient.id}")
            if reply_token:
                await reply_to_line(reply_token, await compose_reply("handoff_to_human", {}))
            return

    if is_autopilot_patient and "いつもの" in text and current_mode not in {
        "waiting_menu", "waiting_datetime", "waiting_time_duration", "autopilot_confirm_usual",
    }:
        preset = await _get_patient_default_preset(db, line_patient)
        if preset:
            usual_draft = {
                "customer_name": line_patient.name,
                "menu_id": preset["menu_id"],
                "menu_name": preset["menu_name"],
                "duration_minutes": preset["duration_minutes"],
            }
            if preset.get("practitioner_id"):
                usual_draft["practitioner_id"] = preset["practitioner_id"]
                usual_draft["practitioner_name"] = preset["practitioner_name"]
            await merge_user_draft(db, user_id, usual_draft)
            await set_user_mode(db, user_id, "waiting_datetime")
            if reply_token:
                await reply_to_line(
                    reply_token,
                    f"いつもの{preset['menu_name']} {preset['duration_minutes']}分"
                    f"{'・担当: ' + preset['practitioner_name'] if preset.get('practitioner_name') else ''}で承ります。"
                    "ご希望日時を教えてくださいね。\n例: 明日 午前中",
                )
            return

    if is_autopilot_patient and current_mode == "autopilot_booking_confirm":
        request_id = user_state.get("request_id")
        request_data = await get_request(db, request_id, line_user_id=user_id) if request_id else None
        polarity = parsed_intent.get("polarity") if parsed_intent else "none"
        if polarity == "negative" or (polarity == "none" and _is_negative(text)):
            await clear_user_draft(db, user_id)
            await set_user_mode(db, user_id, "waiting_datetime", request_id)
            if reply_token:
                await reply_to_line(reply_token, "候補を取りやめました。別のご希望日時を教えてください。")
            return
        if not (polarity == "affirmative" or (polarity == "none" and _is_affirmative(text))) or not request_data or not request_data.get("available"):
            if reply_token:
                await reply_to_line(reply_token, "この候補で予約する場合は「はい」、別の日時を希望する場合は「いいえ」と返信してください。")
            return
        try:
            start_dt = datetime.fromisoformat(request_data["start_time_iso"])
            end_dt = datetime.fromisoformat(request_data["end_time_iso"])
            reservation = await create_reservation(
                db,
                ReservationCreate(
                    patient_id=line_patient.id,
                    practitioner_id=int(request_data["practitioner_id"]),
                    menu_id=request_data.get("menu_id"),
                    start_time=start_dt,
                    end_time=end_dt,
                    channel="LINE",
                    notes="LINE AI秘書 確認後確定",
                ),
                reject_conflicts=True,
            )
        except (HTTPException, ValueError):
            await update_request(db, request_id, line_user_id=user_id, status="alternatives_sent")
            await set_user_mode(db, user_id, "adjusting", request_id)
            if reply_token:
                await reply_to_line(reply_token, "候補枠が直前に埋まりました。別の候補をご案内します。")
            return
        await update_request(db, request_id, line_user_id=user_id, status="confirmed", reservation_id=reservation.get("id"))
        await clear_user_draft(db, user_id)
        await set_user_mode(db, user_id, "idle")
        if reply_token:
            await reply_to_line(reply_token, f"ご予約を確定しました。\n{start_dt.strftime('%Y/%m/%d %H:%M')}〜{end_dt.strftime('%H:%M')}\nご来院をお待ちしております。")
        return

    if is_autopilot_patient and current_mode == "adjusting":
        request_id = user_state.get("request_id")
        request_data = await get_request(db, request_id, line_user_id=user_id) if request_id else None
        alternatives = request_data.get("alternatives") if request_data else None
        selected_choice = _extract_alternative_choice(text, len(alternatives)) if alternatives else None
        if alternatives and selected_choice is not None:
            alternative = alternatives[selected_choice - 1]
            try:
                start_dt = datetime.combine(
                    date.fromisoformat(alternative["date"]),
                    time.fromisoformat(alternative["start"]),
                    tzinfo=JST,
                )
                end_dt = datetime.combine(
                    date.fromisoformat(alternative["date"]),
                    time.fromisoformat(alternative["end"]),
                    tzinfo=JST,
                )
            except (KeyError, TypeError, ValueError):
                if reply_token:
                    await reply_to_line(reply_token, "候補を確認できませんでした。別のご希望日時を教えてください。")
                return
            # 番号選択＝患者の明示的な確定意思。追加の「はい/いいえ」は求めない。
            try:
                reservation = await create_reservation(
                    db,
                    ReservationCreate(
                        patient_id=line_patient.id,
                        practitioner_id=int(alternative["practitioner_id"]),
                        menu_id=request_data.get("menu_id"),
                        start_time=start_dt,
                        end_time=end_dt,
                        channel="LINE",
                        notes="LINE AI秘書 候補選択確定",
                    ),
                    reject_conflicts=True,
                )
            except (HTTPException, ValueError):
                await update_request(db, request_id, line_user_id=user_id, status="alternatives_sent")
                if reply_token:
                    await reply_to_line(reply_token, "その候補は直前に埋まってしまいました。恐れ入りますが別の番号をお選びください。")
                return
            await update_request(db, request_id, line_user_id=user_id, status="confirmed", reservation_id=reservation.get("id"))
            await clear_user_draft(db, user_id)
            await set_user_mode(db, user_id, "idle")
            if reply_token:
                practitioner_name = alternative.get("practitioner_name") or "担当者"
                await reply_to_line(
                    reply_token,
                    "ご予約を確定しました。\n"
                    f"{start_dt.strftime('%Y/%m/%d %H:%M')}〜{end_dt.strftime('%H:%M')}（担当: {practitioner_name}）\n"
                    "ご来院をお待ちしております。",
                )
            return

    if is_autopilot_patient and current_mode == "autopilot_cancel_confirm":
        reservation_id = prev_draft.get("autopilot_cancel_reservation_id")
        if _is_affirmative(text) and reservation_id:
            try:
                await transition_status(db, int(reservation_id), "CANCELLED")
                await db.commit()
            except HTTPException as error:
                await db.rollback()
                await set_user_mode(db, user_id, "autopilot_cancel_confirm")
                logger.warning("LINE autopilot cancellation failed: reservation_id=%s detail=%s", reservation_id, error.detail)
                if reply_token:
                    await reply_to_line(reply_token, "キャンセル処理を完了できませんでした。もう一度「はい」と返信するか、担当者へご連絡ください。")
                return
            await clear_user_draft(db, user_id)
            await set_user_mode(db, user_id, "idle")
            await create_notification(
                db,
                "reservation_cancelled",
                f"LINE予約キャンセル: {line_patient.name}様",
                int(reservation_id),
            )
            if reply_token:
                await reply_to_line(reply_token, "ご予約をキャンセルしました。")
            return
        if _is_negative(text):
            await clear_user_draft(db, user_id)
            await set_user_mode(db, user_id, "idle")
            if reply_token:
                await reply_to_line(reply_token, "キャンセルを取りやめました。")
            return
        if reply_token:
            await reply_to_line(reply_token, "キャンセルする場合は「はい」、取りやめる場合は「いいえ」と返信してください。")
        return

    if is_autopilot_patient and current_mode == "autopilot_change_datetime":
        reservation_id = prev_draft.get("autopilot_change_reservation_id")
        reservation = await db.get(Reservation, int(reservation_id)) if reservation_id else None
        parsed = await parse_line_message(text, profile_name=display_name, previous=prev_draft)
        if not reservation:
            await clear_user_draft(db, user_id)
            await set_user_mode(db, user_id, "idle")
            if reply_token:
                await reply_to_line(reply_token, "変更する予約を確認できませんでした。あらためて「予約変更したい」と送ってください。")
            return
        if not parsed.get("date") or not parsed.get("time"):
            if reply_token:
                await reply_to_line(reply_token, "変更後の日時を教えてください。\n例: 明日の午後3時 / Next Friday at 3 PM")
            return
        await _complete_autopilot_reschedule(
            db,
            reservation=reservation,
            desired_date=parsed["date"],
            desired_time=parsed["time"],
            user_id=user_id,
            reply_token=reply_token,
        )
        return

    if is_autopilot_patient and current_mode == "autopilot_change_confirm":
        reservation_id = prev_draft.get("autopilot_change_reservation_id")
        start_time_iso = prev_draft.get("autopilot_change_start_time_iso")
        end_time_iso = prev_draft.get("autopilot_change_end_time_iso")
        practitioner_id = prev_draft.get("autopilot_change_practitioner_id")
        if _is_negative(text):
            await clear_user_draft(db, user_id)
            await set_user_mode(db, user_id, "autopilot_change_datetime")
            if reply_token:
                await reply_to_line(reply_token, "変更候補を取りやめました。別のご希望日時を教えてください。")
            return
        if not _is_affirmative(text) or not all([reservation_id, start_time_iso, end_time_iso, practitioner_id]):
            if reply_token:
                await reply_to_line(reply_token, "変更する場合は「はい」、別の日時を希望する場合は「いいえ」と返信してください。")
            return
        try:
            start_dt = datetime.fromisoformat(start_time_iso)
            end_dt = datetime.fromisoformat(end_time_iso)
            await reschedule_reservation(db, int(reservation_id), start_dt, end_dt, int(practitioner_id))
        except (HTTPException, ValueError):
            await set_user_mode(db, user_id, "autopilot_change_datetime")
            if reply_token:
                await reply_to_line(reply_token, "候補枠が直前に埋まりました。別のご希望日時を教えてください。")
            return
        await clear_user_draft(db, user_id)
        await set_user_mode(db, user_id, "idle")
        if reply_token:
            await reply_to_line(reply_token, f"ご予約を変更しました。\n{start_dt.strftime('%Y/%m/%d %H:%M')}〜{end_dt.strftime('%H:%M')}\nご来院をお待ちしております。")
        return

    if is_autopilot_patient and current_mode == "autopilot_confirm_usual":
        preset = await _get_patient_default_preset(db, line_patient)
        if not preset:
            await set_user_mode(db, user_id, "waiting_menu")
            if reply_token:
                quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
                await reply_text_with_quick_reply(reply_token, "ご希望メニューを選んでください。", quick_items)
            return
        if _is_affirmative(text):
            usual_draft = {
                "menu_id": preset["menu_id"],
                "menu_name": preset["menu_name"],
                "duration_minutes": preset["duration_minutes"],
            }
            if preset.get("practitioner_id"):
                usual_draft["practitioner_id"] = preset["practitioner_id"]
                usual_draft["practitioner_name"] = preset["practitioner_name"]
            merged = await merge_user_draft(db, user_id, usual_draft)
            # 「うん、それでいいよ。明日の午後どう？」のように同じ文へ日時が含まれる場合は拾う。
            parsed_same = await parse_line_message(text, profile_name=display_name, previous=prev_draft)
            if parsed_same.get("date") or parsed_same.get("time"):
                merged = await merge_user_draft(
                    db,
                    user_id,
                    {
                        "customer_name": (line_patient.name if line_patient else None),
                        "date": parsed_same.get("date"),
                        "time": parsed_same.get("time"),
                    },
                )
            await set_user_mode(db, user_id, "idle")
        elif text.strip() in {"いいえ", "変更", "ちがう", "違う"}:
            await set_user_mode(db, user_id, "waiting_menu")
            if reply_token:
                quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
                await reply_text_with_quick_reply(reply_token, "ご希望メニューを選んでください。", quick_items)
            return
        else:
            if reply_token:
                await reply_to_line(reply_token, _format_usual_confirmation(preset))
            return

    if is_autopilot_patient and (parsed_intent or {}).get("intent") == "question":
        await set_user_mode(db, user_id, "manual")
        await create_notification(db, "line_manual_mode", f"LINE手動対応: {line_patient.id}")
        return

    if is_autopilot_patient and ((parsed_intent or {}).get("intent") == "cancel" or _has_cancellation_intent(text)):
        reservation = await _find_single_upcoming_reservation(db, line_patient.id)
        if not reservation:
            await set_user_mode(db, user_id, "manual")
            await create_notification(db, "line_manual_mode", f"LINEキャンセル要確認: {line_patient.id}")
            return
        await merge_user_draft(db, user_id, {"autopilot_cancel_reservation_id": reservation.id})
        await set_user_mode(db, user_id, "autopilot_cancel_confirm")
        if reply_token:
            await reply_to_line(
                reply_token,
                f"{reservation.start_time.astimezone(JST).strftime('%Y/%m/%d %H:%M')}のご予約をキャンセルしますか？\nはい / いいえ",
            )
        return

    if is_autopilot_patient and ((parsed_intent or {}).get("intent") == "change" or _has_change_intent(text)):
        reservation = await _find_single_upcoming_reservation(db, line_patient.id)
        if not reservation:
            await set_user_mode(db, user_id, "manual")
            await create_notification(db, "line_manual_mode", f"LINE変更要確認: {line_patient.id}")
            return
        parsed_change = await parse_line_message(text, profile_name=display_name, previous=prev_draft)
        desired_date, desired_time = parsed_change.get("date"), parsed_change.get("time")
        if not desired_date or not desired_time:
            await merge_user_draft(db, user_id, {"autopilot_change_reservation_id": reservation.id})
            await set_user_mode(db, user_id, "autopilot_change_datetime")
            if reply_token:
                await reply_to_line(reply_token, "変更後の日時を教えてください。\n例: 明日の午後3時 / Next Friday at 3 PM")
            return
        await _complete_autopilot_reschedule(
            db,
            reservation=reservation,
            desired_date=desired_date,
            desired_time=desired_time,
            user_id=user_id,
            reply_token=reply_token,
        )
        return

    if not line_patient and current_mode not in {"awaiting_name", "awaiting_existing_confirmation", "awaiting_identity_token"}:
        await set_user_mode(db, user_id, "awaiting_name", user_state.get("request_id"))
        await create_notification(db, "line_name_registration", f"LINE初回名前登録待ち: {user_id}")
        if reply_token:
            await reply_to_line(
                reply_token,
                "カルテ登録のため、フルネーム（姓・名）を入力してください。\n例: 田中 太郎",
            )
        return

    if current_mode == "awaiting_name" and not line_patient:
        full_name = extract_full_name(text, profile_name=display_name)
        if not full_name or len(full_name) < 2:
            if reply_token:
                await reply_to_line(reply_token, "確認のため、フルネーム（姓・名）をもう一度お願いします。")
            return

        candidates = await find_name_candidates(db, full_name, limit=5)
        if candidates:
            await merge_user_draft(
                db,
                user_id,
                {
                    "line_input_name": full_name,
                    "line_candidate_ids": [p.id for p in candidates],
                },
            )
            await set_user_mode(db, user_id, "awaiting_existing_confirmation", user_state.get("request_id"))
            if reply_token:
                await reply_text_with_quick_reply(
                    reply_token,
                    "以前当院をご利用したことがありますか？\n"
                    "ある場合は、登録済み情報（電話番号または生年月日）でご本人確認します。",
                    _build_yes_no_new_quick_reply_items(),
                )
            return

        line_patient = await _register_line_patient(db, user_id, full_name)
        await merge_user_draft(db, user_id, {"customer_name": line_patient.name})
        await set_user_mode(db, user_id, "waiting_menu", user_state.get("request_id"))
        await create_notification(db, "line_name_registered", f"LINE初回名前登録完了: {line_patient.name}")
        if reply_token:
            quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
            await reply_text_with_quick_reply(
                reply_token,
                f"{line_patient.name}様、登録ありがとうございます。続けてご希望メニューを選択してください。",
                quick_items,
            )
        return

    if current_mode == "awaiting_existing_confirmation" and not line_patient:
        entered_name = prev_draft.get("line_input_name") or extract_full_name(text, profile_name=display_name) or ""
        normalized_text = text.strip()

        if normalized_text == "はい":
            await set_user_mode(db, user_id, "awaiting_identity_token", user_state.get("request_id"))
            if reply_token:
                await reply_text_with_quick_reply(
                    reply_token,
                    "ご本人確認のため、登録済みの電話番号または生年月日（YYYY-MM-DD）を入力してください。\n"
                    "分からない場合は「新規登録」を選んでください。",
                    [
                        {
                            "type": "action",
                            "action": {"type": "message", "label": "新規登録", "text": "新規登録"},
                        }
                    ],
                )
            return

        if normalized_text in {"いいえ", "新規登録"}:
            line_patient = await _register_line_patient_as_new(db, user_id, entered_name)
            await merge_user_draft(db, user_id, {"customer_name": line_patient.name})
            await set_user_mode(db, user_id, "waiting_menu", user_state.get("request_id"))
            await create_notification(db, "line_name_registered", f"LINE新規登録: {line_patient.name}")
            if reply_token:
                quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
                await reply_text_with_quick_reply(
                    reply_token,
                    f"{line_patient.name}様、新規登録ありがとうございます。続けてご希望メニューを選択してください。",
                    quick_items,
                )
            return

        if reply_token:
            await reply_text_with_quick_reply(
                reply_token,
                "「はい」または「いいえ」を選択してください。",
                _build_yes_no_new_quick_reply_items(),
            )
        return

    if current_mode == "awaiting_identity_token" and not line_patient:
        token = text.strip()
        entered_name = prev_draft.get("line_input_name") or ""
        candidate_ids = prev_draft.get("line_candidate_ids") or []

        if token == "新規登録":
            line_patient = await _register_line_patient_as_new(db, user_id, entered_name)
            await merge_user_draft(db, user_id, {"customer_name": line_patient.name})
            await set_user_mode(db, user_id, "waiting_menu", user_state.get("request_id"))
            await create_notification(db, "line_name_registered", f"LINE新規登録(本人選択): {line_patient.name}")
            if reply_token:
                quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
                await reply_text_with_quick_reply(
                    reply_token,
                    f"{line_patient.name}様、新規登録として受け付けました。続けてご希望メニューを選択してください。",
                    quick_items,
                )
            return

        if not isinstance(candidate_ids, list) or not candidate_ids:
            await set_user_mode(db, user_id, "awaiting_name", user_state.get("request_id"))
            if reply_token:
                await reply_to_line(reply_token, "確認情報が見つからないため、もう一度お名前の入力をお願いします。")
            return

        result = await db.execute(select(Patient).where(Patient.id.in_(candidate_ids)))
        candidates = result.scalars().all()
        matched = [p for p in candidates if match_identity_token(p, token)]

        if len(matched) == 1:
            line_patient = matched[0]
            updated = False
            if not line_patient.line_id:
                line_patient.line_id = user_id
                updated = True
            if entered_name and line_patient.name in {None, "", "不明", "LINE患者"}:
                line_patient.name = entered_name
                updated = True
            if updated:
                await db.flush()

            await merge_user_draft(db, user_id, {"customer_name": line_patient.name})
            await set_user_mode(db, user_id, "waiting_menu", user_state.get("request_id"))
            await create_notification(db, "line_identity_verified", f"LINE既存患者紐づけ: patient_id={line_patient.id}")
            if reply_token:
                quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
                await reply_text_with_quick_reply(
                    reply_token,
                    "ご本人確認ができました。以前の患者情報にLINEを紐づけました。続けてご希望メニューを選択してください。",
                    quick_items,
                )
            return

        if reply_token:
            await reply_text_with_quick_reply(
                reply_token,
                "一致する情報が確認できませんでした。登録済みの電話番号または生年月日（YYYY-MM-DD）を入力してください。\n"
                "分からない場合は「新規登録」を選べます。",
                [
                    {
                        "type": "action",
                        "action": {"type": "message", "label": "新規登録", "text": "新規登録"},
                    }
                ],
            )
        return

    if current_mode == "waiting_menu":
        preset = await _get_patient_default_preset(db, line_patient)
        if text.startswith("⭐️いつもの") and preset:
            draft_update: dict = {
                "customer_name": (line_patient.name if line_patient else None) or prev_draft.get("customer_name"),
                "menu_name": preset["menu_name"],
                "menu_id": preset["menu_id"],
                "duration_minutes": preset["duration_minutes"],
            }
            if preset.get("practitioner_id"):
                draft_update["practitioner_id"] = preset["practitioner_id"]
                draft_update["practitioner_name"] = preset["practitioner_name"]
            await merge_user_draft(db, user_id, draft_update)
            await set_user_mode(db, user_id, "waiting_datetime", user_state.get("request_id"))
            if reply_token:
                if preset.get("practitioner_name"):
                    msg = f"⭐️いつもの内容で承りました（担当: {preset['practitioner_name']}）。\nご希望日時を教えてくださいね。\n例: 明日 10時"
                else:
                    msg = "⭐️いつもの内容で承りました。\nご希望日時を教えてくださいね。\n例: 明日 10時"
                await reply_to_line(reply_token, msg)
            return
        if text.startswith("⭐️いつもの") and latest_reservation:
            await merge_user_draft(
                db,
                user_id,
                {
                    "customer_name": (line_patient.name if line_patient else None) or prev_draft.get("customer_name"),
                    "menu_name": latest_reservation["menu_name"],
                    "menu_id": latest_reservation.get("menu_id"),
                    "duration_minutes": latest_reservation["duration_minutes"],
                },
            )
            await set_user_mode(db, user_id, "waiting_datetime", user_state.get("request_id"))
            if reply_token:
                await reply_to_line(reply_token, "⭐️いつもの内容で承りました。ご希望日時を教えてくださいね。\n例: 明日 10時")
            return

        selected_menu = await _resolve_menu(db, text)
        if not selected_menu:
            if reply_token:
                quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
                await reply_text_with_quick_reply(reply_token, "ご希望メニューを選んでくださいね。", quick_items)
            return

        await merge_user_draft(
            db,
            user_id,
            {
                "customer_name": (line_patient.name if line_patient else None) or prev_draft.get("customer_name"),
                "menu_name": selected_menu.name,
                "menu_id": selected_menu.id,
                "duration_minutes": selected_menu.duration_minutes,
            },
        )

        if selected_menu.is_duration_variable:
            min_minutes, max_minutes = _menu_duration_bounds(selected_menu)
            await set_user_mode(db, user_id, "waiting_time_duration", user_state.get("request_id"))
            if reply_token:
                quick_items = _build_duration_quick_reply_items(min_minutes, max_minutes)
                await reply_text_with_quick_reply(
                    reply_token,
                    f"{selected_menu.name}ですね。施術時間は{min_minutes}〜{max_minutes}分で、10分刻みで選べます。",
                    quick_items,
                )
            return

        await set_user_mode(db, user_id, "waiting_datetime", user_state.get("request_id"))
        if reply_token:
            await reply_to_line(reply_token, f"{selected_menu.name}ですね。ご希望日時を教えてください。\n例: 4/10 10:00")
        return

    if current_mode == "waiting_time_duration":
        menu = await _resolve_menu(db, prev_draft.get("menu_name"))
        if not menu:
            await set_user_mode(db, user_id, "waiting_menu", user_state.get("request_id"))
            if reply_token:
                quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
                await reply_text_with_quick_reply(reply_token, "先にメニューを選んでください。", quick_items)
            return

        duration = _extract_duration_minutes(text)
        min_minutes, max_minutes = _menu_duration_bounds(menu)
        if duration is None or not _is_valid_duration_for_menu(menu, duration):
            if reply_token:
                quick_items = _build_duration_quick_reply_items(min_minutes, max_minutes)
                await reply_text_with_quick_reply(
                    reply_token,
                    f"時間は{min_minutes}〜{max_minutes}分の10分刻みでお願いします。",
                    quick_items,
                )
            return

        await merge_user_draft(db, user_id, {"duration_minutes": duration})
        await set_user_mode(db, user_id, "waiting_datetime", user_state.get("request_id"))
        if reply_token:
            await reply_to_line(reply_token, "ありがとうございます。続いてご希望日時を教えてください。\n例: 明日 10時")
        return

    if current_mode == "waiting_datetime":
        parsed_dt = await parse_line_message(text, profile_name=display_name, previous=prev_draft)
        merged_dt = await merge_user_draft(
            db,
            user_id,
            {
                "customer_name": (line_patient.name if line_patient else None) or parsed_dt.get("customer_name"),
                "date": parsed_dt.get("date"),
                "time": parsed_dt.get("time"),
            },
        )
        if not merged_dt.get("date") or not merged_dt.get("time"):
            if reply_token:
                await reply_to_line(reply_token, await compose_reply("ask_datetime", {}))
            return
        merged = merged_dt

    if merged is None:
        result = await parse_line_message(text, profile_name=display_name, previous=prev_draft)
        if not result or not result.get("has_reservation_intent"):
            if is_autopilot_patient:
                await set_user_mode(db, user_id, "manual")
                await create_notification(db, "line_manual_mode", f"LINE意図不明: {line_patient.id}")
                return
            if reply_token:
                default_msg = await _get_setting(db, "line_reply_default", "メッセージを受け付けました。内容を確認いたします。")
                await reply_to_line(reply_token, default_msg)
            return

        merged = await merge_user_draft(
            db,
            user_id,
            {
                "customer_name": (line_patient.name if line_patient else None) or result.get("customer_name"),
                "date": result.get("date"),
                "time": result.get("time"),
                "menu_name": result.get("menu_name"),
                "parse_confidence": result.get("confidence"),
            },
        )

    if not merged.get("menu_name"):
        preset = await _get_patient_default_preset(db, line_patient) if is_autopilot_patient else None
        if preset:
            await set_user_mode(db, user_id, "autopilot_confirm_usual")
            if reply_token:
                await reply_to_line(reply_token, _format_usual_confirmation(preset))
            return
        await set_user_mode(db, user_id, "waiting_menu", user_state.get("request_id"))
        if reply_token:
            quick_items = await _build_menu_quick_reply_items(db, line_user_id=user_id, patient=line_patient)
            prompt = "ご希望メニューを選んでください。"
            if latest_reservation:
                prompt = "いつもご来院ありがとうございます。今回のご希望メニューを選んでください。"
            await reply_text_with_quick_reply(reply_token, prompt, quick_items)
        return

    menu = await _resolve_menu(db, merged.get("menu_name"))
    if menu:
        await merge_user_draft(db, user_id, {"menu_id": menu.id, "menu_name": menu.name})
        if menu.is_duration_variable and not merged.get("duration_minutes"):
            min_minutes, max_minutes = _menu_duration_bounds(menu)
            await set_user_mode(db, user_id, "waiting_time_duration", user_state.get("request_id"))
            if reply_token:
                quick_items = _build_duration_quick_reply_items(min_minutes, max_minutes)
                await reply_text_with_quick_reply(
                    reply_token,
                    f"{menu.name}は時間を選べます。{min_minutes}〜{max_minutes}分で教えてください。",
                    quick_items,
                )
            return

    missing_datetime = [k for k in ["date", "time"] if not merged.get(k)]
    if missing_datetime:
        await set_user_mode(db, user_id, "waiting_datetime", user_state.get("request_id"))
        if reply_token:
            await reply_to_line(reply_token, _build_missing_info_message(missing_datetime))
        return

    desired_date = merged.get("date")
    desired_time = merged.get("time")
    customer_name = merged.get("customer_name") or (line_patient.name if line_patient else None) or "不明"
    menu_name = merged.get("menu_name")

    duration = int(merged.get("duration_minutes") or 0)
    if menu:
        if duration and _is_valid_duration_for_menu(menu, duration):
            pass
        elif menu.is_duration_variable:
            min_minutes, max_minutes = _menu_duration_bounds(menu)
            await set_user_mode(db, user_id, "waiting_time_duration", user_state.get("request_id"))
            if reply_token:
                quick_items = _build_duration_quick_reply_items(min_minutes, max_minutes)
                await reply_text_with_quick_reply(
                    reply_token,
                    f"施術時間を確認させてください。{min_minutes}〜{max_minutes}分でお願いします。",
                    quick_items,
                )
            return
        else:
            duration = menu.duration_minutes
    if duration <= 0:
        duration = 60

    try:
        target_date = date.fromisoformat(desired_date)
        hh, mm = map(int, str(desired_time).split(":"))
        target_time = time(hh, mm)
    except Exception:
        if reply_token:
            await reply_to_line(reply_token, await compose_reply("parse_failed", {}))
        return

    # ── 担当・施術時間の決定ルール ──
    preferred_practitioner_id = merged.get("practitioner_id")
    prefer_director = False
    first_visit_note: str | None = None
    if is_autopilot_patient:
        requested_prac = await _extract_requested_practitioner(db, text)
        is_new_patient = latest_reservation is None and not preferred_practitioner_id
        if requested_prac:
            # 本人が担当を指名 → その担当固定（院長探索は不要）
            preferred_practitioner_id = requested_prac.id
        if is_new_patient:
            # 完全新規は「HPからの新規獲得」と同ロジック: 院長枠優先＋60分基本固定。
            # ただし本人が長い施術（90分マッスル等）を指定済みならその時間を優先。
            if not requested_prac:
                prefer_director = True
            if duration < 60:
                duration = 60
            first_visit_note = "初回はカウンセリングを含め60分ほどお時間をいただいております。"

    # 候補提示時の優先担当（院長優先の場合は院長IDを解決）
    candidate_practitioner_id = preferred_practitioner_id
    if prefer_director and not candidate_practitioner_id:
        director = (
            await db.execute(
                select(Practitioner)
                .where(Practitioner.is_active == True, Practitioner.role == "院長")
                .order_by(Practitioner.display_order)
            )
        ).scalars().first()
        if director:
            candidate_practitioner_id = director.id

    practitioner, start_dt, end_dt, gap_before, gap_after = await find_best_practitioner(
        db,
        target_date,
        target_time,
        duration,
        prefer_director=prefer_director,
        practitioner_id=preferred_practitioner_id,
    )
    alternatives: list[dict] = []
    vague_choice = False
    needs_candidates = (not practitioner) or (is_autopilot_patient and _has_vague_time_period(text))
    if needs_candidates:
        vague_choice = practitioner is not None  # 空きはあるが曖昧時間帯 → 候補から選ばせる
        if is_autopilot_patient:
            window = _vague_time_window(text)
            scored = await build_same_day_candidates(
                db, target_date, target_time, duration,
                preferred_practitioner_id=candidate_practitioner_id,
                window_start_min=(window[0] if window else None),
                window_end_min=(window[1] if window else None),
                max_results=3,
            )
        else:
            scored = await score_candidates(
                db, target_date, target_time, duration,
                practitioner_id=candidate_practitioner_id, max_results=3,
            )
        alternatives = [s.to_dict() for s in scored]
        practitioner = None

    if practitioner:
        gap_notes = []
        if gap_before > 0:
            earlier = start_dt - timedelta(minutes=gap_before)
            gap_notes.append(f"⚠ 直前{gap_before}分空白（{earlier.strftime('%H:%M')}〜{start_dt.strftime('%H:%M')}）→ 前詰めで連続枠に")
        if gap_after > 0:
            later = end_dt + timedelta(minutes=gap_after)
            gap_notes.append(f"⚠ 直後{gap_after}分空白（{end_dt.strftime('%H:%M')}〜{later.strftime('%H:%M')}）→ 後詰めで連続枠に")
        gap_note = ("\n" + "\n".join(gap_notes)) if gap_notes else ""
        availability_text = (
            f"空きあり: {start_dt.strftime('%Y-%m-%d %H:%M')}〜{end_dt.strftime('%H:%M')}（{practitioner.name}）"
            + gap_note
        )
    elif alternatives:
        alt_lines = "\n".join(
            f"{i}. {a['label']}" for i, a in enumerate(alternatives, 1)
        )
        availability_text = f"希望枠は満席。代替候補:\n{alt_lines}"
    else:
        availability_text = "希望枠は満席。代替候補なし"

    request_id = await create_pending_request(
        db,
        {
            "user_id": user_id,
            "customer_name": customer_name,
            "date": desired_date,
            "time": desired_time,
            "menu_name": menu.name if menu else menu_name,
            "menu_id": menu.id if menu else None,
            "duration_minutes": duration,
            "available": practitioner is not None,
            "practitioner_id": practitioner.id if practitioner else None,
            "alternatives": alternatives,
            "start_time_iso": start_dt.isoformat(),
            "end_time_iso": end_dt.isoformat(),
            "availability_text": availability_text,
        }
    )

    if is_autopilot_patient:
        if practitioner:
            if latest_reservation and merged.get("parse_confidence") == "high":
                try:
                    reservation = await create_reservation(
                        db,
                        ReservationCreate(
                            patient_id=line_patient.id,
                            practitioner_id=practitioner.id,
                            menu_id=menu.id if menu else None,
                            start_time=start_dt,
                            end_time=end_dt,
                            channel="LINE",
                            notes="LINE AI秘書 高確信即時確定",
                        ),
                        reject_conflicts=True,
                    )
                except HTTPException:
                    await update_request(db, request_id, line_user_id=user_id, status="alternatives_sent")
                    await set_user_mode(db, user_id, "waiting_datetime", request_id)
                    if reply_token:
                        await reply_to_line(reply_token, "候補枠が直前に埋まりました。別のご希望日時を教えてください。")
                    return
                else:
                    await update_request(db, request_id, line_user_id=user_id, status="confirmed", reservation_id=reservation.get("id"))
                    await clear_user_draft(db, user_id)
                    await set_user_mode(db, user_id, "idle")
                    if reply_token:
                        await reply_to_line(reply_token, await compose_reply("confirmed", {"start": start_dt.strftime("%Y/%m/%d %H:%M"), "end": end_dt.strftime("%H:%M"), "practitioner": practitioner.name, "menu": menu.name if menu else menu_name}))
                    return
            await update_request(db, request_id, line_user_id=user_id, status="awaiting_patient_confirmation")
            await set_user_mode(db, user_id, "autopilot_booking_confirm", request_id)
            if reply_token:
                await reply_to_line(
                    reply_token,
                    _format_autopilot_slot_confirmation(start_dt, end_dt, practitioner.name, note=first_visit_note),
                )
            return

        await update_request(db, request_id, line_user_id=user_id, status="alternatives_sent")
        await set_user_mode(db, user_id, "adjusting", request_id)
        if reply_token:
            alt_text = _compose_alternatives_text(alternatives, vague=vague_choice)
            if first_visit_note:
                alt_text = f"{first_visit_note}\n{alt_text}"
            await reply_to_line(reply_token, alt_text)
        return

    payload = {
        "request_id": request_id,
        "line_user_id": user_id,
        "customer_name": customer_name,
        "date": desired_date,
        "time": desired_time,
        "menu_name": menu.name if menu else (menu_name or "未指定"),
        "availability_text": availability_text,
    }
    await push_admin_reservation_review(payload)

    await create_notification(
        db,
        "line_proposal",
        f"LINE予約提案: {customer_name}様 {desired_date} {desired_time}",
    )

    if reply_token:
        thanks_prefix = f"{line_patient.name}様、いつもありがとうございます。\n" if line_patient else ""
        ack = await _get_setting(
            db,
            "line_reply_reservation",
            "ありがとうございます。空き状況を確認し、担当者からご案内します。",
        )
        await reply_to_line(reply_token, thanks_prefix + ack)

    await clear_user_draft(db, user_id)
    await set_user_mode(db, user_id, "adjusting", request_id)


async def _handle_postback(event: dict, db: AsyncSession):
    reply_token = event.get("replyToken")
    data_str = event.get("postback", {}).get("data", "")
    if not data_str:
        return

    q = parse_qs(data_str)
    action = (q.get("action") or [""])[0]
    rid = (q.get("rid") or [""])[0]
    line_user_id = (q.get("uid") or [""])[0] or None
    req = await get_request(db, rid, line_user_id=line_user_id)
    if not req:
        if reply_token:
            await reply_to_line(reply_token, "対象の依頼が見つかりません（期限切れの可能性があります）。")
        return

    user_id = req.get("user_id")
    if not user_id:
        if reply_token:
            await reply_to_line(reply_token, "患者情報が不足しているため処理できません。")
        return

    if action == "approve_confirm":
        if not req.get("available"):
            if reply_token:
                await reply_to_line(reply_token, "希望枠は満席のため確定できません。代替案送信を選択してください。")
            return

        patient = await _find_or_create_line_patient(db, user_id, req.get("customer_name"))
        start_dt = datetime.fromisoformat(req["start_time_iso"])
        end_dt = datetime.fromisoformat(req["end_time_iso"])

        reservation = await create_reservation(
            db,
            ReservationCreate(
                patient_id=patient.id,
                practitioner_id=int(req["practitioner_id"]),
                menu_id=req.get("menu_id"),
                start_time=start_dt,
                end_time=end_dt,
                channel="LINE",
                notes=f"LINE AI秘書 確定 (RID:{rid})",
            ),
        )
        await update_request(db, rid, line_user_id=user_id, status="confirmed", reservation_id=reservation.get("id"))
        await set_user_mode(db, user_id, "idle", rid)

        await push_message(
            user_id,
            f"ご予約を確定しました。\n{start_dt.strftime('%Y/%m/%d %H:%M')}〜{end_dt.strftime('%H:%M')}\nご来院をお待ちしております。",
        )
        if reply_token:
            await reply_to_line(reply_token, f"予約を確定しました（予約ID: {reservation.get('id')}）。")

    elif action == "send_alternatives":
        alternatives = req.get("alternatives") or []
        await push_message(user_id, _compose_alternatives_text(alternatives))
        await update_request(db, rid, line_user_id=user_id, status="alternatives_sent")
        await set_user_mode(db, user_id, "adjusting", rid)
        if reply_token:
            await reply_to_line(reply_token, "患者へ代替案を送信しました。")

    elif action == "manual_reply":
        await update_request(db, rid, line_user_id=user_id, status="manual_reply")
        await set_user_mode(db, user_id, "manual", rid)
        if reply_token:
            await reply_to_line(reply_token, "この患者は手動返信モードに切り替えました。")

    # ── シャドーモード: 管理者承認 ──
    elif action == "shadow_approve":
        if not req.get("available"):
            if reply_token:
                await reply_to_line(reply_token, "希望枠は満席のため確定できません。代替案を選択してください。")
            return

        patient = await _get_or_create_shadow_timetable_patient(db, user_id)
        start_dt = datetime.fromisoformat(req["start_time_iso"])
        end_dt = datetime.fromisoformat(req["end_time_iso"])

        duration_minutes = int(req.get("duration_minutes") or ((end_dt - start_dt).total_seconds() // 60))
        date_label = _format_date_with_weekday_jp(start_dt.date())
        time_label = start_dt.strftime("%H:%M")

        try:
            reservation = await create_reservation(
                db,
                ReservationCreate(
                    patient_id=patient.id,
                    practitioner_id=int(req["practitioner_id"]),
                    menu_id=req.get("menu_id"),
                    start_time=start_dt,
                    end_time=end_dt,
                    channel="LINE",
                    notes=f"LINE シャドーモード確定 (RID:{rid}) / dummy_patient={patient.name}",
                ),
            )
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else str(e.detail)
            admin_fail_text = (
                f"予約枠を登録できませんでしたので、手動で対応お願いします。"
                f"{date_label} {time_label}〜{duration_minutes}分です。"
                f" 理由: {detail}"
            )
            await push_message(settings.line_admin_user_id, admin_fail_text)
            if reply_token:
                await reply_to_line(reply_token, admin_fail_text)
            await update_request(db, rid, line_user_id=user_id, status="manual_reply")
            await set_user_mode(db, user_id, "manual", rid)
            return
        except Exception as e:
            admin_fail_text = (
                f"予約枠を登録できませんでしたので、手動で対応お願いします。"
                f"{date_label} {time_label}〜{duration_minutes}分です。"
                f" 理由: {str(e)}"
            )
            await push_message(settings.line_admin_user_id, admin_fail_text)
            if reply_token:
                await reply_to_line(reply_token, admin_fail_text)
            await update_request(db, rid, line_user_id=user_id, status="manual_reply")
            await set_user_mode(db, user_id, "manual", rid)
            return

        # 予約ボード登録後に患者へ通知（ボード先行）
        reservation_status = reservation.get("status")
        await update_request(db, rid, line_user_id=user_id, status=("confirmed" if reservation_status == "CONFIRMED" else "pending"), reservation_id=reservation.get("id"))
        await set_user_mode(db, user_id, "idle", rid)

        if reservation_status == "CONFIRMED":
            simulated_reply = (
                f"ご予約を確定しました。\n"
                f"{start_dt.strftime('%Y/%m/%d %H:%M')}〜{end_dt.strftime('%H:%M')}\n"
                f"ご来院をお待ちしております。"
            )
            admin_ok_text = (
                f"予約システムに登録し予約完了しました。{date_label} {time_label}〜{duration_minutes}分です。"
                f"\nタイムテーブル表示名: {patient.name}"
                f"\n[シャドー送信なし/患者返信想定]\n{simulated_reply}"
            )
        else:
            simulated_reply = (
                f"ご予約リクエストを受け付けました。\n"
                f"{start_dt.strftime('%Y/%m/%d %H:%M')}〜{end_dt.strftime('%H:%M')}\n"
                f"最終確認後にご案内します。"
            )
            admin_ok_text = (
                f"予約システムには登録しましたが、ステータスは{reservation_status}です。"
                f" {date_label} {time_label}〜{duration_minutes}分。最終確認をお願いします。"
                f"\nタイムテーブル表示名: {patient.name}"
                f"\n[シャドー送信なし/患者返信想定]\n{simulated_reply}"
            )

        await push_message(settings.line_admin_user_id, admin_ok_text)
        if reply_token:
            await reply_to_line(reply_token, admin_ok_text)

    elif action == "shadow_alt":
        alt_raw = (q.get("alt") or ["0"])[0]
        try:
            alt_index = int(alt_raw) - 1
        except (TypeError, ValueError):
            if reply_token:
                await reply_to_line(reply_token, "代案番号の形式が不正です。1〜3を選択してください。")
            return
        alternatives = req.get("alternatives") or []
        if alt_index < 0 or alt_index >= len(alternatives):
            if reply_token:
                await reply_to_line(reply_token, "選択された代案が見つかりません。")
            return

        alt = alternatives[alt_index]
        patient = await _get_or_create_shadow_timetable_patient(db, user_id)

        # 代案の日時で予約作成
        alt_date = date.fromisoformat(alt["date"])
        alt_start_str = alt.get("start") or alt.get("start_time", "")
        alt_end_str = alt.get("end") or alt.get("end_time", "")
        hh_s, mm_s = map(int, alt_start_str.split(":"))
        hh_e, mm_e = map(int, alt_end_str.split(":"))
        alt_start_dt = datetime.combine(alt_date, time(hh_s, mm_s), tzinfo=JST)
        alt_end_dt = datetime.combine(alt_date, time(hh_e, mm_e), tzinfo=JST)

        alt_duration_minutes = int((alt_end_dt - alt_start_dt).total_seconds() // 60)
        alt_date_label = _format_date_with_weekday_jp(alt_start_dt.date())
        alt_time_label = alt_start_dt.strftime("%H:%M")

        try:
            reservation = await create_reservation(
                db,
                ReservationCreate(
                    patient_id=patient.id,
                    practitioner_id=int(alt["practitioner_id"]),
                    menu_id=req.get("menu_id"),
                    start_time=alt_start_dt,
                    end_time=alt_end_dt,
                    channel="LINE",
                    notes=f"LINE シャドーモード代案{alt_index + 1} (RID:{rid}) / dummy_patient={patient.name}",
                ),
            )
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else str(e.detail)
            admin_fail_text = (
                f"予約枠を登録できませんでしたので、手動で対応お願いします。"
                f"{alt_date_label} {alt_time_label}〜{alt_duration_minutes}分です。"
                f" 理由: {detail}"
            )
            await push_message(settings.line_admin_user_id, admin_fail_text)
            if reply_token:
                await reply_to_line(reply_token, admin_fail_text)
            await update_request(db, rid, line_user_id=user_id, status="manual_reply")
            await set_user_mode(db, user_id, "manual", rid)
            return
        except Exception as e:
            admin_fail_text = (
                f"予約枠を登録できませんでしたので、手動で対応お願いします。"
                f"{alt_date_label} {alt_time_label}〜{alt_duration_minutes}分です。"
                f" 理由: {str(e)}"
            )
            await push_message(settings.line_admin_user_id, admin_fail_text)
            if reply_token:
                await reply_to_line(reply_token, admin_fail_text)
            await update_request(db, rid, line_user_id=user_id, status="manual_reply")
            await set_user_mode(db, user_id, "manual", rid)
            return

        # 予約ボード登録後に患者へ通知（ボード先行）
        reservation_status = reservation.get("status")
        await update_request(db, rid, line_user_id=user_id, status=("confirmed_alt" if reservation_status == "CONFIRMED" else "pending_alt"), reservation_id=reservation.get("id"))
        await set_user_mode(db, user_id, "idle", rid)

        if reservation_status == "CONFIRMED":
            simulated_reply = (
                f"ご予約を確定しました。\n"
                f"{alt_start_dt.strftime('%Y/%m/%d %H:%M')}〜{alt_end_dt.strftime('%H:%M')}\n"
                f"ご来院をお待ちしております。"
            )
            admin_ok_text = (
                f"予約システムに登録し予約完了しました。"
                f"{alt_date_label} {alt_time_label}〜{alt_duration_minutes}分です。"
                f"\nタイムテーブル表示名: {patient.name}"
                f"\n[シャドー送信なし/患者返信想定]\n{simulated_reply}"
            )
        else:
            simulated_reply = (
                f"ご予約リクエストを受け付けました。\n"
                f"{alt_start_dt.strftime('%Y/%m/%d %H:%M')}〜{alt_end_dt.strftime('%H:%M')}\n"
                f"最終確認後にご案内します。"
            )
            admin_ok_text = (
                f"予約システムには登録しましたが、ステータスは{reservation_status}です。"
                f" {alt_date_label} {alt_time_label}〜{alt_duration_minutes}分。最終確認をお願いします。"
                f"\nタイムテーブル表示名: {patient.name}"
                f"\n[シャドー送信なし/患者返信想定]\n{simulated_reply}"
            )

        await push_message(settings.line_admin_user_id, admin_ok_text)
        if reply_token:
            await reply_to_line(reply_token, admin_ok_text)

    elif action == "shadow_manual":
        await update_request(db, rid, line_user_id=user_id, status="manual_reply")
        await set_user_mode(db, user_id, "manual", rid)
        if reply_token:
            await reply_to_line(reply_token, "手動対応に切り替えました。患者へ直接ご連絡ください。")


async def _handle_admin_text_command(db: AsyncSession, text: str, reply_token: str | None) -> bool:
    """Botくん1号へのDMで管理コマンドを処理。処理したら True を返す。"""
    from app.services.line_state import find_latest_pending_shadow_request

    stripped = (text or "").strip()
    approve_patterns = ["押さえる", "予約ボードを押さえる", "予約ボード押さえる", "確定", "OK", "ok", "承認"]
    reject_patterns = ["保留", "手動", "却下", "NG", "ng"]

    matched_approve = any(stripped == p or stripped.startswith(p) for p in approve_patterns)
    matched_reject = any(stripped == p or stripped.startswith(p) for p in reject_patterns)

    if not (matched_approve or matched_reject):
        return False

    found = await find_latest_pending_shadow_request(db)
    if not found:
        if reply_token:
            await reply_to_line(reply_token, "確定待ちの予約依頼が見つかりません。")
        return True

    patient_uid, rid, req = found

    if matched_reject:
        await update_request(db, rid, line_user_id=patient_uid, status="manual_reply")
        await set_user_mode(db, patient_uid, "manual", rid)
        if reply_token:
            await reply_to_line(reply_token, f"RID:{rid} を手動対応に切り替えました。")
        return True

    # 承認: 仮想 postback イベントを作って既存処理を再利用
    fake_event = {
        "replyToken": reply_token,
        "postback": {"data": f"action=shadow_approve&rid={rid}&uid={patient_uid}"},
    }
    await _handle_postback(fake_event, db)
    return True


@router.post("/webhook")
async def line_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_line_signature: Optional[str] = Header(None),
):
    """LINE Webhook受信（予約意図抽出 -> 空き照会 -> 管理者確認通知）"""
    if not settings.line_channel_access_token or settings.line_channel_access_token == "xxx":
        logger.info("LINE_CHANNEL_ACCESS_TOKEN が未設定のため Webhook をスキップします")
        return {"status": "skipped"}

    body = await request.body()
    _verify_signature(body, x_line_signature)

    payload = json.loads(body)
    await _forward_line_webhook_to_mirror(payload)

    events = payload.get("events", [])
    for event in events:
        if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
            await _handle_text_message(event, db)
        elif event.get("type") == "postback":
            await _handle_postback(event, db)

    await db.commit()
    return {"status": "ok"}


@router.post("/mirror-webhook")
async def line_mirror_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_line_mirror_secret: Optional[str] = Header(None),
):
    """本番LINE Webhookの複製をstagingで受ける内部専用エンドポイント。"""
    if not settings.line_mirror_shared_secret:
        raise HTTPException(status_code=404, detail="LINE mirror is not configured")
    if not x_line_mirror_secret or not hmac.compare_digest(x_line_mirror_secret, settings.line_mirror_shared_secret):
        raise HTTPException(status_code=403, detail="LINE mirror secret is invalid")

    payload = await request.json()
    label = payload.get("mirror", {}).get("label") if isinstance(payload.get("mirror"), dict) else None
    label = label or settings.line_mirror_label or "STAGING-MIRROR"

    processed = 0
    for event in payload.get("events", []):
        if event.get("type") != "message" or event.get("message", {}).get("type") != "text":
            continue
        source = event.get("source", {})
        user_id = source.get("userId", "")
        text = event.get("message", {}).get("text", "")
        if not user_id:
            continue
        await handle_shadow_message(
            db,
            user_id=user_id,
            text=text,
            display_name=_mirror_display_name(event, label),
        )
        processed += 1

    await db.commit()
    return {"status": "ok", "processed": processed, "label": label}


@router.post("/parse-message")
async def parse_message(body: LineMessageRequest, db: AsyncSession = Depends(get_db)):
    """LINEメッセージ解析（テスト用）"""
    try:
        result = await parse_line_message(body.message)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析に失敗しました: {str(e)}")


@router.get("/flex-template-sample")
async def flex_template_sample():
    """管理者通知用Flex Message JSONテンプレートを返す"""
    sample_payload = {
        "request_id": "sample123",
        "customer_name": "田中太郎",
        "date": now_jst().date().isoformat(),
        "time": "10:00",
        "menu_name": "骨盤矯正",
        "availability_text": "空きあり: 2026-04-04 10:00〜10:45 / 院長",
    }
    return build_reservation_review_flex(sample_payload)
