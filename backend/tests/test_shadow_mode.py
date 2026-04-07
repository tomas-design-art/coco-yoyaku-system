"""シャドーモードのユニットテスト"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# SQLAlchemy relationship 解決のため全モデルをプリロード
import app.models.reservation_color  # noqa: F401
import app.models.menu  # noqa: F401
import app.models.patient  # noqa: F401
import app.models.reservation  # noqa: F401

# ── shadow_service 単体テスト ──


def test_has_reservation_intent_positive():
    from app.services.shadow_service import has_reservation_intent
    assert has_reservation_intent("明日予約したいです")
    assert has_reservation_intent("空きありますか")
    assert has_reservation_intent("キャンセルお願いします")
    assert has_reservation_intent("10時の時間で取りたい")


def test_has_reservation_intent_negative():
    from app.services.shadow_service import has_reservation_intent
    assert not has_reservation_intent("ありがとうございます")
    assert not has_reservation_intent("了解しました")
    assert not has_reservation_intent("こんにちは")


def test_format_admin_notification():
    from app.services.shadow_service import format_admin_notification
    result = format_admin_notification(
        display_name="田中太郎",
        user_id="U1234567890abcdef",
        raw_message="明日10時に予約したいです",
        analysis={
            "intent": "予約希望",
            "name": "田中太郎",
            "menu": None,
            "date": "2026-04-07",
            "time": "10:00",
            "confidence": "high",
        },
    )
    assert "【シャドーモード解析結果】" in result
    assert "田中太郎" in result
    assert "予約希望" in result
    assert "2026-04-07" in result
    assert "10:00" in result


def test_debounce_message_merges():
    from app.services.shadow_service import _DEBOUNCE_BUFFER, debounce_message, flush_debounce
    _DEBOUNCE_BUFFER.clear()

    # 初回：バッファに入る → flush で取得
    result1 = debounce_message("user_a", "明日")
    assert result1 is None  # まだ確定しない（初回はバッファ開始）

    current = flush_debounce("user_a")
    assert current == "明日"
    _DEBOUNCE_BUFFER.clear()


def test_debounce_flushes_previous():
    import time as _time
    from app.services.shadow_service import _DEBOUNCE_BUFFER, _DEBOUNCE_SECONDS, debounce_message
    _DEBOUNCE_BUFFER.clear()

    # 1つ目をバッファに入れる
    debounce_message("user_b", "最初のメッセージ")

    # タイムスタンプを古くして次のメッセージを送る
    _DEBOUNCE_BUFFER["user_b"]["ts"] -= (_DEBOUNCE_SECONDS + 1)
    result = debounce_message("user_b", "2番目のメッセージ")

    # 古いバッファがフラッシュされて返る
    assert result == "最初のメッセージ"
    _DEBOUNCE_BUFFER.clear()


# ── シャドーモード Webhook 統合テスト ──


@pytest.mark.asyncio
async def test_shadow_mode_bypasses_normal_flow():
    """SHADOW_MODE=True のとき、状態遷移も reply も行わずに 200 を返す"""
    from app.services.shadow_service import _DEBOUNCE_BUFFER
    _DEBOUNCE_BUFFER.clear()

    with patch("app.api.line.settings") as mock_settings, \
         patch("app.api.line._get_line_display_name", new_callable=AsyncMock, return_value="テスト太郎"), \
         patch("app.api.line.handle_shadow_message", new_callable=AsyncMock) as mock_handle, \
         patch("app.api.line.reply_to_line", new_callable=AsyncMock) as mock_reply, \
         patch("app.api.line.create_notification", new_callable=AsyncMock):

        mock_settings.shadow_mode = True
        mock_settings.line_channel_secret = ""

        mock_db = AsyncMock()

        event = {
            "type": "message",
            "message": {"type": "text", "text": "明日予約したい"},
            "source": {"userId": "U_TEST_SHADOW"},
            "replyToken": "test_token_123",
        }
        from app.api.line import _handle_text_message
        await _handle_text_message(event, mock_db)

        mock_handle.assert_awaited_once()
        call_kwargs = mock_handle.call_args.kwargs
        assert call_kwargs["user_id"] == "U_TEST_SHADOW"
        assert call_kwargs["text"] == "明日予約したい"

        # reply は一切呼ばれない
        mock_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_shadow_mode_off_normal_flow_unchanged():
    """SHADOW_MODE=False のときは通常フローが動く（handle_shadow_message は呼ばれない）"""
    with patch("app.api.line.settings") as mock_settings, \
         patch("app.api.line.handle_shadow_message", new_callable=AsyncMock) as mock_handle, \
         patch("app.api.line.create_notification", new_callable=AsyncMock), \
         patch("app.api.line.get_user_mode", new_callable=AsyncMock, return_value="idle"), \
         patch("app.api.line.get_user_state", new_callable=AsyncMock, return_value={"draft": {}, "mode": None}), \
         patch("app.api.line._get_line_display_name", new_callable=AsyncMock, return_value="テスト"), \
         patch("app.api.line._find_line_patient", new_callable=AsyncMock, return_value=None), \
         patch("app.api.line.set_user_mode", new_callable=AsyncMock), \
         patch("app.api.line.reply_to_line", new_callable=AsyncMock):

        mock_settings.shadow_mode = False
        mock_settings.line_channel_secret = ""

        mock_db = AsyncMock()

        event = {
            "type": "message",
            "message": {"type": "text", "text": "こんにちは"},
            "source": {"userId": "U_TEST_NORMAL"},
            "replyToken": "test_token_456",
        }
        from app.api.line import _handle_text_message
        await _handle_text_message(event, mock_db)

        # シャドー処理は呼ばれない
        mock_handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_shadow_no_intent_logs_only():
    """予約意図がないメッセージはログのみ保存し通知しない"""
    from app.services.shadow_service import _DEBOUNCE_BUFFER
    _DEBOUNCE_BUFFER.clear()

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    with patch("app.services.shadow_service.analyze_with_llm", new_callable=AsyncMock) as mock_llm, \
         patch("app.services.shadow_service.notify_admin_shadow", new_callable=AsyncMock) as mock_notify:

        from app.services.shadow_service import handle_shadow_message
        await handle_shadow_message(
            mock_db,
            user_id="U_NO_INTENT",
            text="ありがとうございます",
            display_name="山田",
        )

        # 予約意図なし → LLM も通知も呼ばれない
        mock_llm.assert_not_awaited()
        mock_notify.assert_not_awaited()

        # ただしDBログは保存される
        mock_db.add.assert_called()


@pytest.mark.asyncio
async def test_shadow_with_intent_analyzes_and_notifies():
    """予約意図ありのメッセージはLLM解析 + 管理者通知 + ログ保存"""
    from app.services.shadow_service import _DEBOUNCE_BUFFER
    _DEBOUNCE_BUFFER.clear()

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.flush = AsyncMock()

    analysis = {
        "intent": "予約希望",
        "name": "鈴木",
        "menu": "骨盤矯正",
        "date": "2026-04-07",
        "time": "14:00",
        "confidence": "high",
    }

    with patch("app.services.shadow_service.analyze_with_llm", new_callable=AsyncMock, return_value=analysis) as mock_llm, \
         patch("app.services.shadow_service.notify_admin_shadow", new_callable=AsyncMock, return_value=True) as mock_notify:

        from app.services.shadow_service import handle_shadow_message
        await handle_shadow_message(
            mock_db,
            user_id="U_WITH_INTENT",
            text="明日14時に骨盤矯正の予約お願いします",
            display_name="鈴木",
        )

        mock_llm.assert_awaited_once()
        mock_notify.assert_awaited_once()
        mock_db.add.assert_called()
