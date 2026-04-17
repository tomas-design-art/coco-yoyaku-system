"""シャドーモード: 患者に返信せず管理者にのみ解析結果を通知するサービス"""
from __future__ import annotations

import json
import logging
import re
import time as _time
from datetime import date, datetime, time, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.patient import Patient
from app.models.shadow_log import ShadowLog
from app.services.line_reply import push_message_with_access_token
from app.services.line_state import (
    clear_user_draft,
    create_pending_request,
    get_user_state,
    merge_user_draft,
    set_user_mode,
)
from app.utils.datetime_jst import JST, now_jst

logger = logging.getLogger(__name__)

# ── デバウンス用バッファ（user_id → {text, ts}) ──
_DEBOUNCE_BUFFER: dict[str, dict] = {}
_DEBOUNCE_SECONDS = 10

# ── 予約意図キーワード ──
_RESERVATION_KEYWORDS = [
    "予約", "よやく", "空き", "あき", "取りたい", "お願い",
    "受診", "見てもら", "診てもら", "空いて", "空きますか",
    "キャンセル", "変更", "時間", "日時", "何時", "いつ", "相談", "問合せ", "問い合わせ",
]

# ── LLMプロンプト ──
_SHADOW_PARSE_PROMPT = """\
あなたは接骨院のLINE予約アシスタントです。
以下の患者メッセージから予約に関する情報を抽出し、必ず**JSONのみ**で返してください。
説明文は禁止。今日の日付は {today} です。

出力JSON形式（必ず全キーを含めること）:
{{
    "intent": "予約希望 | 変更 | キャンセル | 遅刻 | 相談 | その他",
    "content": "患者の要望を1〜2文で簡潔に要約",
    "name": "患者名 or null",
    "menu": null,
    "date": "YYYY-MM-DD or null",
    "time": "HH:MM or null",
    "duration_minutes": 整数 or null,
    "confidence": "high | medium | low"
}}

重要:
- メニューの推定は不要。`menu` は常に null で良い。
- 最優先で `date` と `time` を抽出する。
- 意図は必ず6分類から1つを選ぶ。
- 「遅刻」は遅れる旨の報告。
- 施術時間に言及があれば `duration_minutes` に分数を入れる。
- `content` は患者の要望を簡潔に日本語で要約する（例: "明日14時に60分の予約を希望"）。

患者メッセージ:
{message}

JSON:
"""


def has_reservation_intent(text: str) -> bool:
    """予約意図キーワードを含むか判定"""
    if any(kw in text for kw in _RESERVATION_KEYWORDS):
        return True
    date_val, time_val = _extract_date_time_rule(text)
    return bool(date_val or time_val)


def _extract_intent_rule(text: str) -> str:
    if re.search(r"キャンセル|取り消|取消|なしで|やめ|辞退", text):
        return "キャンセル"
    if re.search(r"変更|変え|ずら|移動|リスケ|別日", text):
        return "変更"
    if re.search(r"遅れ|遅刻|遅く|間に合わ|少し遅れ", text):
        return "遅刻"
    if re.search(r"相談|そうだん|問合せ|問い合わせ|確認したい|聞きたい", text):
        return "相談"
    if re.search(r"予約|よやく|空き|あき|取りたい|お願い|受診|見てもら|診てもら", text):
        return "予約希望"
    return "その他"


def _extract_date_time_rule(text: str) -> tuple[str | None, str | None]:
    now = now_jst()
    dval: str | None = None
    tval: str | None = None

    # Relative date
    if "明後日" in text:
        dval = (now.date() + timedelta(days=2)).isoformat()
    elif "明日" in text:
        dval = (now.date() + timedelta(days=1)).isoformat()
    elif "今日" in text:
        dval = now.date().isoformat()

    # Absolute date (YYYY/MM/DD, YYYY-MM-DD)
    m_abs = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", text)
    if m_abs:
        y, mo, da = int(m_abs.group(1)), int(m_abs.group(2)), int(m_abs.group(3))
        dval = f"{y:04d}-{mo:02d}-{da:02d}"
    else:
        # Absolute date (M/D, M月D日)
        m_md = re.search(r"(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?", text)
        if m_md:
            mo, da = int(m_md.group(1)), int(m_md.group(2))
            y = now.year + (1 if mo < now.month else 0)
            dval = f"{y:04d}-{mo:02d}-{da:02d}"

    # Time: HH:MM
    m_hm = re.search(r"(\d{1,2})\s*[:：]\s*(\d{1,2})", text)
    if m_hm:
        hh = int(m_hm.group(1))
        mm = int(m_hm.group(2))
        if "午後" in text and 1 <= hh <= 11:
            hh += 12
        tval = f"{hh:02d}:{mm:02d}"
    else:
        # Time: HH時半 / HH時
        m_h = re.search(r"(午前|午後)?\s*(\d{1,2})\s*時\s*(半)?", text)
        if m_h:
            hh = int(m_h.group(2))
            mm = 30 if m_h.group(3) else 0
            if m_h.group(1) == "午後" and 1 <= hh <= 11:
                hh += 12
            tval = f"{hh:02d}:{mm:02d}"

    return dval, tval


def _normalize_analysis(analysis: dict, message: str) -> dict:
    rule_intent = _extract_intent_rule(message)
    rule_date, rule_time = _extract_date_time_rule(message)
    rule_duration = _extract_duration_rule(message)
    parsed = dict(analysis or {})

    valid_intents = {"予約希望", "変更", "キャンセル", "遅刻", "相談", "その他"}
    intent = parsed.get("intent")
    parsed["intent"] = intent if intent in valid_intents else rule_intent

    parsed["date"] = parsed.get("date") or rule_date
    parsed["time"] = parsed.get("time") or rule_time
    parsed["menu"] = None

    # duration
    dur = parsed.get("duration_minutes")
    if isinstance(dur, (int, float)) and dur > 0:
        parsed["duration_minutes"] = int(dur)
    else:
        parsed["duration_minutes"] = rule_duration

    conf = parsed.get("confidence")
    if conf not in {"high", "medium", "low"}:
        parsed["confidence"] = "medium" if (parsed.get("date") or parsed.get("time")) else "low"

    for key in ("name", "content"):
        parsed.setdefault(key, None)

    return parsed


def _extract_duration_rule(text: str) -> int | None:
    """メッセージから施術時間（分）を抽出"""
    m = re.search(r"(\d{2,3})\s*分", text)
    if m:
        val = int(m.group(1))
        if 10 <= val <= 300:
            return val
    return None


def _rule_based_shadow_parse(message: str) -> dict:
    date_val, time_val = _extract_date_time_rule(message)
    duration = _extract_duration_rule(message)
    intent = _extract_intent_rule(message)
    confidence = "high" if (date_val and time_val) else ("medium" if (date_val or time_val) else "low")
    return {
        "intent": intent,
        "content": None,
        "name": None,
        "menu": None,
        "date": date_val,
        "time": time_val,
        "duration_minutes": duration,
        "confidence": confidence,
    }


def debounce_message(user_id: str, text: str) -> str | None:
    """同一ユーザーの連続メッセージを統合。統合結果を返すか、まだ待機中ならNone。

    呼び出し側は最初のメッセージ到着から _DEBOUNCE_SECONDS 後に
    flush_debounce() を呼ぶ設計だが、シンプルに
    「前回から _DEBOUNCE_SECONDS 以内なら結合、超えたら確定」で実装する。
    """
    now = _time.time()
    entry = _DEBOUNCE_BUFFER.get(user_id)

    if entry and (now - entry["ts"]) < _DEBOUNCE_SECONDS:
        # 統合: テキストを改行で追記
        entry["text"] = entry["text"] + "\n" + text
        entry["ts"] = now
        return None  # まだ確定しない

    # 前回のバッファが残っていればフラッシュ
    flushed: str | None = None
    if entry:
        flushed = entry["text"]

    # 新しいバッファを開始
    _DEBOUNCE_BUFFER[user_id] = {"text": text, "ts": now}

    return flushed


def flush_debounce(user_id: str) -> str | None:
    """バッファに残っているメッセージを強制確定して返す"""
    entry = _DEBOUNCE_BUFFER.pop(user_id, None)
    return entry["text"] if entry else None


async def analyze_with_llm(message: str) -> dict:
    """Gemini APIでシャドーモード用JSON解析"""
    today = now_jst().date().isoformat()
    prompt = _SHADOW_PARSE_PROMPT.format(today=today, message=message)

    if not settings.gemini_api_key:
        logger.warning("GEMINI_API_KEY not set; using rule-based shadow analysis")
        return _rule_based_shadow_parse(message)

    model = settings.gemini_model
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={settings.gemini_api_key}"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 512},
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                # 必要キーの保証
                for key in ("intent", "name", "menu", "date", "time", "confidence"):
                    parsed.setdefault(key, None)
                return _normalize_analysis(parsed, message)
    except Exception as e:
        logger.error("Shadow LLM analysis failed: %s", e)

    return _rule_based_shadow_parse(message)


def _empty_result() -> dict:
    return {
        "intent": None,
        "content": None,
        "name": None,
        "menu": None,
        "date": None,
        "time": None,
        "confidence": None,
    }


def _generate_content_summary(analysis: dict, draft: dict | None = None) -> str:
    """解析結果から内容要約を自動生成（LLM content がなければフォールバック）"""
    content = analysis.get("content")
    if content and content != "null" and content.strip():
        return content.strip()

    intent = analysis.get("intent") or "不明"
    src = draft if draft else analysis
    parts = []
    if src.get("date"):
        parts.append(src["date"])
    if src.get("time"):
        parts.append(src["time"])
    if src.get("duration_minutes"):
        parts.append(f"{src['duration_minutes']}分")

    time_info = " ".join(parts) if parts else ""

    if intent == "予約希望":
        return f"予約希望{' (' + time_info + ')' if time_info else ''}"
    elif intent == "変更":
        return "予約の変更を希望"
    elif intent == "キャンセル":
        return "予約のキャンセルを希望"
    elif intent == "遅刻":
        return "遅刻の連絡"
    elif intent == "相談":
        return "予約に関する相談"
    return "その他"


async def save_shadow_log(
    db: AsyncSession,
    *,
    line_user_id: str,
    display_name: str | None,
    raw_message: str,
    has_intent: bool,
    analysis: dict | None,
    notified: bool,
) -> ShadowLog:
    """解析ログをDBに保存"""
    log = ShadowLog(
        line_user_id=line_user_id,
        display_name=display_name,
        raw_message=raw_message,
        has_reservation_intent=has_intent,
        analysis_result=analysis,
        notified=notified,
    )
    db.add(log)
    await db.flush()
    return log


def format_admin_notification(
    *,
    display_name: str | None,
    user_id: str,
    raw_message: str,
    analysis: dict,
) -> str:
    """管理者向け通知テキストを整形"""
    ts = now_jst().strftime("%Y-%m-%d %H:%M")
    name = display_name or "不明"
    content = _generate_content_summary(analysis)
    date_str = analysis.get("date") or "未抽出"
    time_str = analysis.get("time") or "未抽出"
    desired_time = f"{date_str} {time_str}" if date_str != "未抽出" else "未抽出"
    lines = [
        f"📩 {name}さんからのメッセージ ({ts})",
        "",
        "【原文】",
        raw_message[:300],
        "",
        f"【分類】{analysis.get('intent') or '不明'}",
        f"【内容】{content}",
        f"【患者希望の予約時間】{desired_time}",
    ]
    return "\n".join(lines)


async def notify_admin_shadow(
    *,
    display_name: str | None,
    user_id: str,
    raw_message: str,
    analysis: dict,
) -> bool:
    """管理者（ADMIN_LINE_DEVELOPER_USER_ID）にPush通知"""
    target = settings.admin_line_developer_user_id
    token = settings.line_channel_developer_access_token
    if not target or not token:
        # developer 用が未設定なら通常管理者へフォールバック
        target = settings.line_admin_user_id
        token = settings.line_channel_access_token
    if not target or not token:
        logger.warning("Shadow notify skipped: no admin user ID or token configured")
        return False

    text = format_admin_notification(
        display_name=display_name,
        user_id=user_id,
        raw_message=raw_message,
        analysis=analysis,
    )
    return await push_message_with_access_token(target, text, token)


async def handle_shadow_message(
    db: AsyncSession,
    *,
    user_id: str,
    text: str,
    display_name: str | None,
) -> None:
    """シャドーモードのメイン処理（多ターン予約ドラフト対応）

    1. デバウンスで連続メッセージを統合
    2. 予約意図判定 → 意図なしはログのみ
    3. LLM解析 → ドラフト蓄積 → 情報揃ったら空き確認 → 管理者通知
    """

    # ── デバウンス処理 ──
    flushed = debounce_message(user_id, text)
    messages_to_process: list[str] = []
    if flushed:
        messages_to_process.append(flushed)
    current = flush_debounce(user_id)
    if current and current not in messages_to_process:
        messages_to_process.append(current)

    for msg in messages_to_process:
        intent_detected = has_reservation_intent(msg)

        # ── 既存ドラフトがあるか確認 ──
        user_state = await get_user_state(db, user_id)
        current_mode = user_state.get("mode")
        prev_draft = user_state.get("draft") or {}
        is_shadow_drafting = current_mode == "shadow_drafting"

        # 管理者対応待ち or 手動モード → 追加メッセージを管理者へ転送のみ
        if current_mode in {"shadow_pending_admin", "manual"}:
            await _push_admin_text(
                f"📨 {display_name or '不明'}さんから追加メッセージ:\n{msg[:200]}"
            )
            await save_shadow_log(
                db,
                line_user_id=user_id,
                display_name=display_name,
                raw_message=msg,
                has_intent=False,
                analysis=None,
                notified=True,
            )
            continue

        if not intent_detected and not is_shadow_drafting:
            await save_shadow_log(
                db,
                line_user_id=user_id,
                display_name=display_name,
                raw_message=msg,
                has_intent=False,
                analysis=None,
                notified=False,
            )
            logger.info("Shadow: no reservation intent, logged only (user=%s)", user_id[:12])
            continue

        # ── LLM解析 ──
        analysis = await analyze_with_llm(msg)
        intent = analysis.get("intent") or ""

        # 予約希望以外の意図（変更・キャンセル・遅刻・相談）は手動対応へ切替
        if intent in {"変更", "キャンセル", "遅刻", "相談"}:
            notified = await notify_admin_shadow(
                display_name=display_name,
                user_id=user_id,
                raw_message=msg,
                analysis=analysis,
            )
            await clear_user_draft(db, user_id)
            await set_user_mode(db, user_id, "manual", user_state.get("request_id"))
            await save_shadow_log(
                db,
                line_user_id=user_id,
                display_name=display_name,
                raw_message=msg,
                has_intent=True,
                analysis=analysis,
                notified=notified,
            )
            logger.info("Shadow: intent=%s → switched to manual mode (user=%s)", intent, user_id[:12])
            continue

        # ── 予約ドラフト蓄積 ──
        if not is_shadow_drafting:
            await set_user_mode(db, user_id, "shadow_drafting")
            # 患者情報取得
            patient = await _find_line_patient(db, user_id)
            patient_name = display_name or (patient.name if patient else None) or "不明"
            await merge_user_draft(db, user_id, {"customer_name": patient_name})

            # 「いつものお願いします」チェック
            if re.search(r"いつもの|いつも通り|前回と同じ", msg):
                preset = await _get_patient_default_preset(db, patient)
                if preset:
                    await merge_user_draft(db, user_id, {
                        "duration_minutes": preset["duration_minutes"],
                        "menu_name": preset.get("menu_name"),
                        "menu_id": preset.get("menu_id"),
                        "practitioner_id": preset.get("practitioner_id"),
                        "practitioner_name": preset.get("practitioner_name"),
                    })
                    logger.info("Shadow: applied patient defaults for user=%s", user_id[:12])

        # ドラフトにマージ
        draft_update: dict = {}
        if analysis.get("date"):
            draft_update["date"] = analysis["date"]
        if analysis.get("time"):
            draft_update["time"] = analysis["time"]
        if analysis.get("duration_minutes"):
            draft_update["duration_minutes"] = analysis["duration_minutes"]
        if analysis.get("name") and analysis["name"] != "null":
            draft_update["customer_name"] = analysis["name"]
        if analysis.get("content"):
            draft_update["content"] = analysis["content"]

        # 原文をドラフトに蓄積
        existing_raw = prev_draft.get("raw_messages") or ""
        draft_update["raw_messages"] = (existing_raw + "\n" + msg).strip()

        await merge_user_draft(db, user_id, draft_update)

        # 最新ドラフトを再取得
        user_state = await get_user_state(db, user_id)
        merged = user_state.get("draft") or {}

        # ── 必要情報チェック: date + time 必須、duration は patient defaults でフォールバック ──
        has_date = bool(merged.get("date"))
        has_time = bool(merged.get("time"))
        has_duration = bool(merged.get("duration_minutes"))

        # duration 未指定でも患者デフォルトがあればフォールバック
        if not has_duration:
            patient = await _find_line_patient(db, user_id)
            preset = await _get_patient_default_preset(db, patient)
            if preset:
                await merge_user_draft(db, user_id, {"duration_minutes": preset["duration_minutes"]})
                has_duration = True
            elif not has_duration:
                # 最終フォールバック: 60分
                await merge_user_draft(db, user_id, {"duration_minutes": 60})
                has_duration = True

        if has_date and has_time and has_duration:
            # ── 情報揃った → 空き確認 → 管理者通知 ──
            merged = (await get_user_state(db, user_id)).get("draft") or {}
            await _shadow_check_and_notify(db, user_id=user_id, display_name=display_name, draft=merged)
            await save_shadow_log(
                db,
                line_user_id=user_id,
                display_name=display_name,
                raw_message=msg,
                has_intent=True,
                analysis=analysis,
                notified=True,
            )
        else:
            # まだ情報不足 → 管理者に進捗通知
            missing = []
            if not has_date:
                missing.append("日付")
            if not has_time:
                missing.append("時間")
            status_msg = _format_draft_progress(
                display_name=display_name,
                user_id=user_id,
                raw_message=msg,
                draft=merged,
                missing=missing,
            )
            await _push_admin_text(status_msg)
            await save_shadow_log(
                db,
                line_user_id=user_id,
                display_name=display_name,
                raw_message=msg,
                has_intent=True,
                analysis=analysis,
                notified=True,
            )
            logger.info("Shadow: draft incomplete, missing=%s (user=%s)", missing, user_id[:12])


# ── 曜日表記ヘルパー ──
_WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def _format_date_with_weekday(d: date) -> str:
    """4/11(土) 形式"""
    wd = _WEEKDAY_JP[d.weekday()]
    return f"{d.month}/{d.day}({wd})"


async def _find_line_patient(db: AsyncSession, user_id: str) -> Patient | None:
    result = await db.execute(
        select(Patient).where(Patient.line_id == user_id).limit(1)
    )
    return result.scalar_one_or_none()


async def _get_patient_default_preset(db: AsyncSession, patient: Patient | None) -> dict | None:
    """患者のデフォルト設定（メニュー・時間・担当者）を返す"""
    if not patient or not patient.default_menu_id:
        return None
    from app.models.menu import Menu
    from app.models.practitioner import Practitioner

    menu = (
        await db.execute(select(Menu).where(Menu.id == patient.default_menu_id, Menu.is_active == True))
    ).scalar_one_or_none()
    if not menu:
        return None
    duration = patient.default_duration or menu.duration_minutes
    practitioner_id = None
    practitioner_name = None
    if patient.preferred_practitioner_id:
        practitioner = (
            await db.execute(select(Practitioner).where(Practitioner.id == patient.preferred_practitioner_id))
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


def _format_draft_progress(
    *,
    display_name: str | None,
    user_id: str,
    raw_message: str,
    draft: dict,
    missing: list[str],
) -> str:
    """管理者向けドラフト進捗通知テキスト"""
    ts = now_jst().strftime("%H:%M")
    name = display_name or "不明"
    lines = [
        f"📝 予約抽出中: {name}",
        f"受信 {ts}: {raw_message[:120]}",
        "── 抽出済み ──",
    ]
    if draft.get("date"):
        lines.append(f"日付: {draft['date']}")
    if draft.get("time"):
        lines.append(f"時間: {draft['time']}")
    if draft.get("duration_minutes"):
        lines.append(f"施術時間: {draft['duration_minutes']}分")
    if missing:
        lines.append(f"⏳ 未抽出: {', '.join(missing)}")
    return "\n".join(lines)


async def _push_admin_text(text: str) -> bool:
    """管理者にテキスト通知"""
    target = settings.line_admin_user_id
    token = settings.line_channel_access_token
    if not target or not token:
        return False
    return await push_message_with_access_token(target, text, token)


async def _shadow_check_and_notify(
    db: AsyncSession,
    *,
    user_id: str,
    display_name: str | None,
    draft: dict,
) -> None:
    """ドラフト完了後: 空き確認 → Flex Message で管理者通知"""
    from app.services.slot_scorer import find_best_practitioner, score_candidates
    from app.services.line_alerts import push_admin_reservation_review
    from app.services.line_reply import push_flex_message
    from app.services.conflict_detector import get_conflicting_reservations

    desired_date_str = draft.get("date")
    desired_time_str = draft.get("time")
    duration = int(draft.get("duration_minutes") or 60)
    customer_name = draft.get("customer_name") or display_name or "不明"

    try:
        target_date = date.fromisoformat(desired_date_str)
        hh, mm = map(int, str(desired_time_str).split(":"))
        target_time = time(hh, mm)
    except Exception:
        logger.error("Shadow: invalid date/time in draft: %s %s", desired_date_str, desired_time_str)
        return

    date_label = _format_date_with_weekday(target_date)

    # ── 空き確認 ──
    practitioner, start_dt, end_dt, gap_before, gap_after = await find_best_practitioner(
        db, target_date, target_time, duration
    )

    alternatives: list[dict] = []
    conflict_info = ""
    if not practitioner:
        # 全施術者のコンフリクトを取得して表示
        from app.models.practitioner import Practitioner as PracModel
        prac_q = await db.execute(
            select(PracModel).where(PracModel.is_active == True).order_by(PracModel.display_order)
        )
        all_pracs = list(prac_q.scalars().all())
        for p in all_pracs:
            conflicts = await get_conflicting_reservations(db, p.id, start_dt, end_dt)
            if conflicts:
                for c in conflicts:
                    pt_name = c.patient.name if c.patient else "不明"
                    c_start = c.start_time.astimezone(JST).strftime("%H:%M") if c.start_time else "?"
                    c_end = c.end_time.astimezone(JST).strftime("%H:%M") if c.end_time else "?"
                    conflict_info = f"予約済み: {pt_name}様 {c_start}〜{c_end}（{p.name}）"
                    break
            if conflict_info:
                break

        scored = await score_candidates(db, target_date, target_time, duration, max_results=3)
        alternatives = [s.to_dict() for s in scored]

    # ── request 作成 ──
    request_id = await create_pending_request(
        db,
        {
            "user_id": user_id,
            "customer_name": customer_name,
            "date": desired_date_str,
            "time": desired_time_str,
            "menu_name": draft.get("menu_name") or "未指定",
            "menu_id": draft.get("menu_id"),
            "duration_minutes": duration,
            "available": practitioner is not None,
            "practitioner_id": practitioner.id if practitioner else None,
            "practitioner_name": practitioner.name if practitioner else None,
            "alternatives": alternatives,
            "start_time_iso": start_dt.isoformat(),
            "end_time_iso": end_dt.isoformat(),
            "conflict_info": conflict_info,
            "gap_before": gap_before if practitioner else 0,
            "gap_after": gap_after if practitioner else 0,
            "shadow_mode": True,
        },
    )

    # ── Flex Message 構築 ──
    raw_messages = draft.get("raw_messages") or ""
    content_summary = _generate_content_summary(
        {"intent": "予約希望", "content": draft.get("content")}, draft
    )
    if practitioner:
        flex = _build_shadow_available_flex(
            request_id=request_id,
            user_id=user_id,
            customer_name=customer_name,
            date_label=date_label,
            time_str=desired_time_str,
            duration=duration,
            practitioner_name=practitioner.name,
            gap_before=gap_before,
            gap_after=gap_after,
            start_dt=start_dt,
            end_dt=end_dt,
            raw_message=raw_messages,
            content_summary=content_summary,
        )
        alt_text = f"予約確認: {customer_name}様 {date_label} {desired_time_str} 空きあり"
    else:
        flex = _build_shadow_conflict_flex(
            request_id=request_id,
            user_id=user_id,
            customer_name=customer_name,
            date_label=date_label,
            time_str=desired_time_str,
            duration=duration,
            conflict_info=conflict_info,
            alternatives=alternatives,
            raw_message=raw_messages,
            content_summary=content_summary,
        )
        alt_text = f"予約確認: {customer_name}様 {date_label} {desired_time_str} 満席"

    pushed = await push_flex_message(settings.line_admin_user_id, alt_text, flex)
    if pushed:
        await set_user_mode(db, user_id, "shadow_pending_admin", request_id)
        await clear_user_draft(db, user_id)
        logger.info(
            "Shadow: draft complete → admin notified (user=%s, rid=%s, available=%s)",
            user_id[:12], request_id, practitioner is not None,
        )
        return

    # Flex通知失敗時は手動運用へフォールバック
    fallback_text = (
        f"[要手動対応] LINE予約通知の送信に失敗しました。\n"
        f"患者: {customer_name}\n希望: {desired_date_str} {desired_time_str} {duration}分\n"
        f"RID: {request_id}\n"
        f"運用: 院長が手動返信後、予約ボードを手動更新してください。"
    )
    await _push_admin_text(fallback_text)
    await set_user_mode(db, user_id, "manual", request_id)
    await clear_user_draft(db, user_id)
    logger.error(
        "Shadow: flex push failed, switched to manual mode (user=%s, rid=%s)",
        user_id[:12], request_id,
    )


def _build_shadow_available_flex(
    *,
    request_id: str,
    user_id: str,
    customer_name: str,
    date_label: str,
    time_str: str,
    duration: int,
    practitioner_name: str,
    gap_before: int,
    gap_after: int,
    start_dt: datetime,
    end_dt: datetime,
    raw_message: str = "",
    content_summary: str = "",
) -> dict:
    """空きあり時の管理者通知 Flex Message（原文→分類→内容→希望時間→枠の状況）"""
    uid_suffix = f"&uid={user_id}" if user_id else ""
    end_time_str = end_dt.strftime("%H:%M")

    body_contents: list[dict] = [
        # 原文セクション
        {"type": "text", "text": "【原文】", "size": "xs", "color": "#6B7280", "weight": "bold"},
        {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": raw_message[:300] or "—", "wrap": True, "size": "sm"}
            ],
            "backgroundColor": "#F3F4F6",
            "paddingAll": "8px",
            "cornerRadius": "4px",
            "margin": "xs",
        },
        {"type": "separator", "margin": "md"},
        # 分類
        {"type": "text", "text": f"【分類】予約希望", "size": "sm", "weight": "bold", "margin": "md"},
        # 内容
        {"type": "text", "text": f"【内容】{content_summary}", "wrap": True, "size": "sm"},
        # 患者希望の予約時間
        {
            "type": "text",
            "text": f"【患者希望の予約時間】{date_label} {time_str}〜{end_time_str}（{duration}分）",
            "wrap": True,
            "size": "sm",
        },
        {"type": "separator", "margin": "md"},
        # 枠の状況
        {
            "type": "text",
            "text": f"【枠の状況】✅ {practitioner_name} 空きあり",
            "wrap": True,
            "size": "sm",
            "color": "#16A34A",
            "weight": "bold",
            "margin": "md",
        },
    ]

    # 前後の空き状況を常に表示
    gap_lines: list[str] = []
    if gap_before == 0:
        gap_lines.append(f"前: 直前まで予約あり（詰まっています）")
    else:
        earlier = start_dt - timedelta(minutes=gap_before)
        gap_lines.append(f"前: {gap_before}分空き（{earlier.strftime('%H:%M')}〜{start_dt.strftime('%H:%M')}）")
    if gap_after == 0:
        gap_lines.append(f"後: 直後に予約あり（詰まっています）")
    else:
        later = end_dt + timedelta(minutes=gap_after)
        gap_lines.append(f"後: {gap_after}分空き（{end_dt.strftime('%H:%M')}〜{later.strftime('%H:%M')}）")

    for gl in gap_lines:
        body_contents.append(
            {"type": "text", "text": gl, "wrap": True, "size": "xs", "color": "#6B7280"}
        )

    # 大きな空白がある場合は時間調整の提案
    if gap_before >= 30 or gap_after >= 30:
        suggest_parts = []
        if gap_before >= 30:
            tighter = start_dt - timedelta(minutes=min(gap_before, 30))
            suggest_parts.append(f"{tighter.strftime('%H:%M')}〜に前倒し")
        if gap_after >= 30:
            tighter = start_dt + timedelta(minutes=min(gap_after, 30))
            suggest_parts.append(f"{tighter.strftime('%H:%M')}〜に後ろ倒し")
        body_contents.append(
            {"type": "text", "text": f"💡 {' or '.join(suggest_parts)}すると枠を詰められます", "wrap": True, "size": "xs", "color": "#2563EB"}
        )

    body_contents.append({"type": "separator", "margin": "md"})
    body_contents.append({"type": "text", "text": f"RID: {request_id}", "size": "xs", "color": "#9CA3AF"})

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"📩 {customer_name}様 LINE予約確認",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#ffffff",
                }
            ],
            "backgroundColor": "#16A34A",
            "paddingAll": "12px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#16A34A",
                    "action": {
                        "type": "postback",
                        "label": "はい・予約確定",
                        "data": f"action=shadow_approve&rid={request_id}{uid_suffix}",
                        "displayText": "はい・予約確定",
                    },
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "いいえ・手動対応",
                        "data": f"action=shadow_manual&rid={request_id}{uid_suffix}",
                        "displayText": "いいえ",
                    },
                },
            ],
        },
    }


def _build_shadow_conflict_flex(
    *,
    request_id: str,
    user_id: str,
    customer_name: str,
    date_label: str,
    time_str: str,
    duration: int,
    conflict_info: str,
    alternatives: list[dict],
    raw_message: str = "",
    content_summary: str = "",
) -> dict:
    """満席時の管理者通知 Flex Message（原文→分類→内容→希望時間→枠の状況→提案3件）"""
    uid_suffix = f"&uid={user_id}" if user_id else ""

    body_contents: list[dict] = [
        # 原文セクション
        {"type": "text", "text": "【原文】", "size": "xs", "color": "#6B7280", "weight": "bold"},
        {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": raw_message[:300] or "—", "wrap": True, "size": "sm"}
            ],
            "backgroundColor": "#F3F4F6",
            "paddingAll": "8px",
            "cornerRadius": "4px",
            "margin": "xs",
        },
        {"type": "separator", "margin": "md"},
        # 分類
        {"type": "text", "text": f"【分類】予約希望", "size": "sm", "weight": "bold", "margin": "md"},
        # 内容
        {"type": "text", "text": f"【内容】{content_summary}", "wrap": True, "size": "sm"},
        # 患者希望の予約時間
        {
            "type": "text",
            "text": f"【患者希望の予約時間】{date_label} {time_str}（{duration}分）",
            "wrap": True,
            "size": "sm",
        },
        {"type": "separator", "margin": "md"},
    ]

    # 枠の状況
    if conflict_info:
        body_contents.append(
            {"type": "text", "text": f"【枠の状況】❌ {conflict_info}", "wrap": True, "size": "sm", "color": "#DC2626", "weight": "bold", "margin": "md"}
        )
    else:
        body_contents.append(
            {"type": "text", "text": "【枠の状況】❌ 希望枠は満席です", "wrap": True, "size": "sm", "color": "#DC2626", "weight": "bold", "margin": "md"}
        )

    # 提案
    if alternatives:
        body_contents.append({"type": "separator", "margin": "md"})
        body_contents.append(
            {"type": "text", "text": "【提案】", "size": "sm", "weight": "bold", "margin": "md"}
        )
        for i, alt in enumerate(alternatives, 1):
            label = alt.get("label", f"候補{i}")
            body_contents.append(
                {"type": "text", "text": f"  {_num_to_circled(i)} {label}", "wrap": True, "size": "sm"}
            )

    body_contents.append({"type": "separator", "margin": "md"})
    body_contents.append({"type": "text", "text": f"RID: {request_id}", "size": "xs", "color": "#9CA3AF"})

    # ボタン: 代案1〜3 + その他
    buttons = []
    for i, alt in enumerate(alternatives[:3], 1):
        buttons.append({
            "type": "button",
            "style": "primary",
            "color": "#2563EB",
            "action": {
                "type": "postback",
                "label": f"{_num_to_circled(i)} {alt.get('start', '')}〜 {alt.get('practitioner_name', '')}",
                "data": f"action=shadow_alt&rid={request_id}&alt={i}{uid_suffix}",
                "displayText": f"{_num_to_circled(i)} を選択",
            },
        })
    buttons.append({
        "type": "button",
        "style": "secondary",
        "action": {
            "type": "postback",
            "label": "④ その他（手動対応）",
            "data": f"action=shadow_manual&rid={request_id}{uid_suffix}",
            "displayText": "その他（手動対応）",
        },
    })

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"📩 {customer_name}様 LINE予約確認（満席）",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#ffffff",
                }
            ],
            "backgroundColor": "#DC2626",
            "paddingAll": "12px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": body_contents,
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": buttons,
        },
    }


def _num_to_circled(n: int) -> str:
    """1→①, 2→②, 3→③"""
    circled = {1: "①", 2: "②", 3: "③", 4: "④"}
    return circled.get(n, str(n))
