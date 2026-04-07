"""LINE AI秘書（第1段階）テスト"""
from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import AsyncMock, patch
from datetime import datetime

import pytest


def test_build_reservation_review_flex_has_three_actions():
    from app.services.line_alerts import build_reservation_review_flex

    flex = build_reservation_review_flex(
        {
            "request_id": "rid123",
            "customer_name": "田中太郎",
            "date": "2026-04-04",
            "time": "10:00",
            "menu_name": "骨盤矯正",
            "availability_text": "空きあり",
        }
    )

    buttons = flex["footer"]["contents"]
    labels = [b["action"]["label"] for b in buttons]
    assert labels == ["承認・確定", "代替案を送る", "自分で返信"]
    assert all("rid=rid123" in b["action"]["data"] for b in buttons)


def test_sos_message_has_fixed_operational_format():
    from app.services.line_alerts import _build_sos_message

    msg = _build_sos_message(
        title="HotPepperポーリング処理で例外が発生しました",
        detail="connection timeout",
        source="hotpepper_poll_job",
        occurred_at=datetime(2026, 4, 5, 10, 30, 0),
    )

    assert "[SOS] 予約システム異常通知" in msg
    assert "重要度: MEDIUM" in msg
    assert "障害機能: HotPepperポーリングジョブ" in msg
    assert "概要: HotPepperポーリング処理で例外が発生しました" in msg
    assert "詳細: connection timeout" in msg
    assert "一次対応:" in msg


def test_sos_message_uses_source_mapping_for_feature_name():
    from app.services.line_alerts import _build_sos_message

    msg = _build_sos_message(
        title="アプリ起動時のDB接続に失敗しました",
        detail=None,
        source="startup_db_check",
        occurred_at=datetime(2026, 4, 5, 9, 0, 0),
    )

    assert "障害機能: 起動時DB接続" in msg
    assert "重要度: HIGH" in msg
    assert "一次対応: DBコンテナ起動状態とDATABASE_URLのホスト名を確認してください。" in msg


def test_sos_message_becomes_high_on_error_type_or_streak():
    from app.services.line_alerts import _build_sos_message

    msg_by_type = _build_sos_message(
        title="DB接続エラー",
        detail="connect timeout",
        source="hotpepper_poll",
        occurred_at=datetime(2026, 4, 5, 9, 5, 0),
        error_type="ConnectionError",
        failure_streak=1,
    )
    assert "重要度: HIGH" in msg_by_type
    assert "例外種別: ConnectionError" in msg_by_type
    assert "連続失敗回数: 1" in msg_by_type

    msg_by_streak = _build_sos_message(
        title="HotPepperメール取得に失敗しました",
        detail="status=error",
        source="hotpepper_poll",
        occurred_at=datetime(2026, 4, 5, 9, 10, 0),
        error_type="PollErrorStatus",
        failure_streak=3,
    )
    assert "重要度: HIGH" in msg_by_streak
    assert "連続失敗回数: 3" in msg_by_streak


def test_recovered_message_has_fixed_operational_format():
    from app.services.line_alerts import _build_recovered_message

    msg = _build_recovered_message(
        source="hotpepper_poll",
        title="HotPepperメール取得が復旧しました",
        started_at=datetime(2026, 4, 5, 10, 0, 0),
        recovered_at=datetime(2026, 4, 5, 10, 5, 30),
        latest_detail="{'status': 'ok', 'processed': 1}",
    )

    assert "[RECOVERED] 予約システム復旧通知" in msg
    assert "障害機能: HotPepperメール取得" in msg
    assert "停止時間: 5分30秒" in msg
    assert "状態: 正常稼働に復帰しました" in msg


@pytest.mark.asyncio
async def test_sos_and_recovered_use_developer_access_token_and_same_destination():
    import app.services.line_alerts as la

    la._ACTIVE_INCIDENTS.clear()
    la._LAST_SOS_SENT.clear()

    with patch("app.services.line_alerts.settings.admin_line_developer_user_id", "U-dev-1"), patch(
        "app.services.line_alerts.settings.line_channel_developer_access_token", "DEV_TOKEN"
    ), patch(
        "app.services.line_alerts.push_message_with_access_token", new=AsyncMock(return_value=True)
    ) as mock_push:
        ok1 = await la.push_developer_sos_alert(
            "HotPepperメール取得に失敗しました",
            detail="timeout",
            source="hotpepper_poll",
            dedupe_key="incident-1",
        )
        ok2 = await la.push_developer_recovered_alert(
            dedupe_key="incident-1",
            title="HotPepperメール取得が復旧しました",
            source="hotpepper_poll",
            latest_detail="ok",
        )

    assert ok1 is True
    assert ok2 is True
    assert mock_push.await_count == 2
    first_call = mock_push.await_args_list[0]
    second_call = mock_push.await_args_list[1]
    assert first_call.args[0] == "U-dev-1"
    assert second_call.args[0] == "U-dev-1"
    assert first_call.args[2] == "DEV_TOKEN"
    assert second_call.args[2] == "DEV_TOKEN"


@pytest.mark.asyncio
async def test_hotpepper_parse_failure_pushes_admin_line_alert():
    from app.services.hotpepper_mail import process_hotpepper_email

    db = AsyncMock()
    with patch("app.services.hotpepper_mail.parse_hotpepper_mail", side_effect=ValueError("parse error")), patch(
        "app.services.line_alerts.push_admin_hotpepper_failure", new=AsyncMock(return_value=True)
    ) as mock_push:
        result = await process_hotpepper_email(db, "invalid mail body")

    assert result["status"] == "error"
    assert "parse error" in result["reason"]
    mock_push.assert_awaited_once()


@pytest.mark.asyncio
async def test_line_parser_extracts_name_menu_datetime_from_natural_japanese():
    from app.agents.line_parser import parse_line_message

    msg = "はじめての受診です。田中 五郎丸 保険診療希望 明日の10時から予約できますか？"
    parsed = await parse_line_message(msg)

    assert parsed["has_reservation_intent"] is True
    assert parsed["customer_name"] == "田中五郎丸"
    assert parsed["menu_name"] == "保険診療"
    assert parsed["date"] is not None
    assert parsed["time"] == "10:00"


def test_missing_info_message_contains_required_labels():
    from app.api.line import _build_missing_info_message

    text = _build_missing_info_message(["customer_name", "menu_name"])
    assert "お名前" in text
    assert "ご希望メニュー" in text


def test_extract_full_name_for_first_time_registration():
    from app.agents.line_parser import extract_full_name

    assert extract_full_name("カルテ用に 田中 太郎 です") == "田中太郎"


@pytest.mark.asyncio
async def test_unregistered_user_gets_full_name_prompt():
    from app.api.line import _handle_text_message

    db = AsyncMock()
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-first"},
        "message": {"type": "text", "text": "予約したいです"},
    }

    with patch("app.api.line.create_notification", new=AsyncMock(return_value=True)), patch(
        "app.api.line._find_line_patient", new=AsyncMock(return_value=None)
    ), patch("app.api.line._get_line_display_name", new=AsyncMock(return_value="たろ")), patch(
        "app.api.line.reply_to_line", new=AsyncMock(return_value=True)
    ) as mock_reply, patch("app.api.line.get_user_mode", new=AsyncMock(return_value=None)), patch(
        "app.api.line.get_user_state", new=AsyncMock(return_value={"request_id": None})
    ), patch("app.api.line.set_user_mode", new=AsyncMock(return_value=None)) as mock_set_mode:
        await _handle_text_message(event, db)

    mock_set_mode.assert_awaited_once()
    assert mock_set_mode.await_args.args[2] == "awaiting_name"
    assert "フルネーム" in mock_reply.await_args.args[1]


@pytest.mark.asyncio
async def test_missing_menu_uses_quick_reply_buttons():
    from app.api.line import _handle_text_message

    db = AsyncMock()
    result = Mock()
    scalar_result = Mock()
    scalar_result.all.return_value = []
    result.scalars.return_value = scalar_result
    db.execute = AsyncMock(return_value=result)
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-known"},
        "message": {"type": "text", "text": "明日の10時でお願いします"},
    }
    patient = type("PatientStub", (), {"name": "田中太郎"})()

    with patch("app.api.line.create_notification", new=AsyncMock(return_value=True)), patch(
        "app.api.line._find_line_patient", new=AsyncMock(return_value=patient)
    ), patch("app.api.line._get_line_display_name", new=AsyncMock(return_value="田中")), patch(
        "app.api.line.get_user_mode", new=AsyncMock(return_value=None)
    ), patch(
        "app.api.line.get_user_state", new=AsyncMock(return_value={"request_id": None, "draft": {}})
    ), patch(
        "app.api.line.merge_user_draft",
        new=AsyncMock(
            return_value={
                "customer_name": "田中太郎",
                "date": "2026-04-05",
                "time": "10:00",
                "menu_name": None,
            }
        ),
    ), patch(
        "app.api.line.set_user_mode", new=AsyncMock(return_value=None)
    ), patch(
        "app.api.line.parse_line_message",
        new=AsyncMock(
            return_value={
                "has_reservation_intent": True,
                "customer_name": "田中太郎",
                "date": "2026-04-05",
                "time": "10:00",
                "menu_name": None,
            }
        ),
    ), patch("app.api.line.reply_text_with_quick_reply", new=AsyncMock(return_value=True)) as mock_quick:
        await _handle_text_message(event, db)

    assert mock_quick.await_count == 1


@pytest.mark.asyncio
async def test_waiting_menu_usual_shortcut_warps_to_waiting_datetime():
    from app.api.line import _handle_text_message

    db = AsyncMock()
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-repeat"},
        "message": {"type": "text", "text": "⭐️いつもの（保険診療 60分）"},
    }
    patient = type("PatientStub", (), {"name": "田中太郎"})()

    with patch("app.api.line.create_notification", new=AsyncMock(return_value=True)), patch(
        "app.api.line.get_user_mode", new=AsyncMock(return_value=None)
    ), patch(
        "app.api.line.get_user_state",
        new=AsyncMock(return_value={"mode": "waiting_menu", "request_id": None, "draft": {"customer_name": "田中太郎"}}),
    ), patch("app.api.line._find_line_patient", new=AsyncMock(return_value=patient)), patch(
        "app.api.line._get_line_display_name", new=AsyncMock(return_value="田中")
    ), patch(
        "app.api.line._get_latest_reservation_for_line_user",
        new=AsyncMock(return_value={"menu_id": 1, "menu_name": "保険診療", "duration_minutes": 60}),
    ), patch("app.api.line.merge_user_draft", new=AsyncMock(return_value={})), patch(
        "app.api.line.set_user_mode", new=AsyncMock(return_value=None)
    ) as mock_set_mode, patch(
        "app.api.line.reply_to_line", new=AsyncMock(return_value=True)
    ):
        await _handle_text_message(event, db)

    mock_set_mode.assert_awaited_once()
    assert mock_set_mode.await_args.args[2] == "waiting_datetime"


@pytest.mark.asyncio
async def test_waiting_time_duration_accepts_10min_step_and_moves_to_datetime():
    from app.api.line import _handle_text_message

    db = AsyncMock()
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-duration"},
        "message": {"type": "text", "text": "50分"},
    }
    patient = type("PatientStub", (), {"name": "田中太郎"})()
    menu = type(
        "MenuStub",
        (),
        {"name": "保険診療", "duration_minutes": 30, "max_duration_minutes": 90, "is_duration_variable": True},
    )()

    with patch("app.api.line.create_notification", new=AsyncMock(return_value=True)), patch(
        "app.api.line.get_user_mode", new=AsyncMock(return_value=None)
    ), patch(
        "app.api.line.get_user_state",
        new=AsyncMock(return_value={"mode": "waiting_time_duration", "request_id": None, "draft": {"menu_name": "保険診療"}}),
    ), patch("app.api.line._find_line_patient", new=AsyncMock(return_value=patient)), patch(
        "app.api.line._get_line_display_name", new=AsyncMock(return_value="田中")
    ), patch(
        "app.api.line._get_latest_reservation_for_line_user", new=AsyncMock(return_value=None)
    ), patch("app.api.line._resolve_menu", new=AsyncMock(return_value=menu)), patch(
        "app.api.line.merge_user_draft", new=AsyncMock(return_value={"duration_minutes": 50})
    ) as mock_merge, patch(
        "app.api.line.set_user_mode", new=AsyncMock(return_value=None)
    ) as mock_set_mode, patch(
        "app.api.line.reply_to_line", new=AsyncMock(return_value=True)
    ):
        await _handle_text_message(event, db)

    assert mock_merge.await_args.args[2]["duration_minutes"] == 50
    assert mock_set_mode.await_args.args[2] == "waiting_datetime"
