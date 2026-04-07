"""シャドーモード: 患者に返信せず管理者にのみ解析結果を通知するサービス"""
from __future__ import annotations

import json
import logging
import re
import time as _time
from datetime import date

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.shadow_log import ShadowLog
from app.services.line_reply import push_message_with_access_token
from app.utils.datetime_jst import now_jst

logger = logging.getLogger(__name__)

# ── デバウンス用バッファ（user_id → {text, ts}) ──
_DEBOUNCE_BUFFER: dict[str, dict] = {}
_DEBOUNCE_SECONDS = 10

# ── 予約意図キーワード ──
_RESERVATION_KEYWORDS = [
    "予約", "よやく", "空き", "あき", "取りたい", "お願い",
    "受診", "見てもら", "診てもら", "空いて", "空きますか",
    "キャンセル", "変更", "時間", "日時", "何時", "いつ",
]

# ── LLMプロンプト ──
_SHADOW_PARSE_PROMPT = """\
あなたは接骨院のLINE予約アシスタントです。
以下の患者メッセージから予約に関する情報を抽出し、必ず**JSONのみ**で返してください。
説明文は禁止。今日の日付は {today} です。

出力JSON形式（必ず全キーを含めること）:
{{
  "intent": "予約希望 | 空き確認 | 変更 | キャンセル | その他",
  "name": "患者名 or null",
  "menu": "メニュー名 or null",
  "date": "YYYY-MM-DD or null",
  "time": "HH:MM or null",
  "confidence": "high | medium | low"
}}

患者メッセージ:
{message}

JSON:
"""


def has_reservation_intent(text: str) -> bool:
    """予約意図キーワードを含むか判定"""
    return any(kw in text for kw in _RESERVATION_KEYWORDS)


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
        logger.warning("GEMINI_API_KEY not set; returning empty analysis")
        return _empty_result()

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
                return parsed
    except Exception as e:
        logger.error("Shadow LLM analysis failed: %s", e)

    return _empty_result()


def _empty_result() -> dict:
    return {
        "intent": None,
        "name": None,
        "menu": None,
        "date": None,
        "time": None,
        "confidence": None,
    }


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
    lines = [
        "【シャドーモード解析結果】",
        f"受信時刻: {ts}",
        f"LINEユーザー: {name} ({user_id[:12]}…)",
        f"原文: {raw_message[:200]}",
        "── 解析結果 ──",
        f"意図: {analysis.get('intent') or '不明'}",
        f"患者名: {analysis.get('name') or '未抽出'}",
        f"メニュー: {analysis.get('menu') or '未抽出'}",
        f"日付: {analysis.get('date') or '未抽出'}",
        f"時間: {analysis.get('time') or '未抽出'}",
        f"確信度: {analysis.get('confidence') or '—'}",
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
    """シャドーモードのメイン処理

    1. デバウンスで連続メッセージを統合
    2. 予約意図判定 → 意図なしはログのみ
    3. LLM解析 → 管理者通知 → DBログ保存
    """
    # ── デバウンス処理 ──
    flushed = debounce_message(user_id, text)

    # flushed=None → 今のメッセージはバッファに追加された（まだ確定しない）
    # ただしHTTP応答は即座に返す必要があるため、
    # 「バッファに追加されたメッセージ」もここで処理する。
    # → 簡易実装: 前回フラッシュ分があればそれも処理し、
    #   新しいバッファも即時フラッシュして処理する
    messages_to_process: list[str] = []
    if flushed:
        messages_to_process.append(flushed)

    # 現在バッファに溜まっている分をフラッシュ
    current = flush_debounce(user_id)
    if current and current not in messages_to_process:
        messages_to_process.append(current)

    for msg in messages_to_process:
        intent_detected = has_reservation_intent(msg)

        if not intent_detected:
            # 予約意図なし → ログのみ保存、通知しない
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

        # ── 管理者通知 ──
        notified = await notify_admin_shadow(
            display_name=display_name,
            user_id=user_id,
            raw_message=msg,
            analysis=analysis,
        )

        # ── DBログ保存 ──
        await save_shadow_log(
            db,
            line_user_id=user_id,
            display_name=display_name,
            raw_message=msg,
            has_intent=True,
            analysis=analysis,
            notified=notified,
        )
        logger.info("Shadow: analyzed & notified=%s (user=%s)", notified, user_id[:12])
