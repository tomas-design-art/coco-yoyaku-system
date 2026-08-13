"""LINE テキストの短時間マージと重複 webhook 検知。"""
from __future__ import annotations

import re
import time

_DEBOUNCE_BUFFER: dict[str, dict] = {}
_DEBOUNCE_SECONDS = 10
_RECENT_MESSAGES: dict[tuple[str, str], float] = {}
_DEDUP_SECONDS = 8


def debounce_message(user_id: str, text: str) -> str | None:
    """同一ユーザーの連続メッセージを統合し、古いドラフトだけを返す。"""
    now = time.time()
    entry = _DEBOUNCE_BUFFER.get(user_id)

    if entry and (now - entry["ts"]) < _DEBOUNCE_SECONDS:
        entry["text"] = entry["text"] + "\n" + text
        entry["ts"] = now
        return None

    flushed = entry["text"] if entry else None
    _DEBOUNCE_BUFFER[user_id] = {"text": text, "ts": now}
    return flushed


def flush_debounce(user_id: str) -> str | None:
    """バッファに残っているメッセージを強制確定して返す。"""
    entry = _DEBOUNCE_BUFFER.pop(user_id, None)
    return entry["text"] if entry else None


def clear_debounce(user_id: str) -> None:
    """会話を再開する際に、そのユーザーの未完了本文を破棄する。"""
    _DEBOUNCE_BUFFER.pop(user_id, None)


def merge_debounced_message(user_id: str, text: str) -> str:
    """直近の分割送信を積み上げ、現在の解析対象本文を返す。"""
    debounce_message(user_id, text)
    entry = _DEBOUNCE_BUFFER.get(user_id)
    return str(entry["text"]) if entry else text


def is_duplicate_message(user_id: str, text: str) -> bool:
    """短時間に同じユーザー・同じ本文が再配信された場合は True を返す。"""
    now = time.time()
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        return False

    expired = [key for key, timestamp in _RECENT_MESSAGES.items() if now - timestamp > _DEDUP_SECONDS]
    for key in expired:
        _RECENT_MESSAGES.pop(key, None)

    key = (user_id, normalized)
    last_seen = _RECENT_MESSAGES.get(key)
    _RECENT_MESSAGES[key] = now
    return last_seen is not None and now - last_seen <= _DEDUP_SECONDS