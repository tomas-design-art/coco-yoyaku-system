"""LINE AI秘書（第1段階）テスト"""
from __future__ import annotations

from unittest.mock import Mock
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from types import SimpleNamespace

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


def test_line_parser_resolves_morning_and_next_sunday_in_real_time():
    from app.agents.line_parser import _extract_date_time
    from app.utils.datetime_jst import now_jst

    tomorrow = now_jst().date() + timedelta(days=1)
    next_sunday_days = (6 - now_jst().weekday()) % 7 or 7
    next_sunday = now_jst().date() + timedelta(days=next_sunday_days)

    tomorrow_date, tomorrow_time = _extract_date_time("明日の午前中空いてますか？")
    sunday_date, _ = _extract_date_time("次の日曜日に予約したい")

    assert tomorrow_date == tomorrow.isoformat()
    assert tomorrow_time == "10:00"
    assert sunday_date == next_sunday.isoformat()


def test_line_parser_reuses_shadow_datetime_normalization_rules():
    from app.agents.line_parser import _extract_date_time

    afternoon_date, afternoon_time = _extract_date_time("2026-08-15の午後3時半に予約したい")
    _, courtesy_time = _extract_date_time("夜分遅くに失礼します。明日空いていますか？")

    assert afternoon_date == "2026-08-15"
    assert afternoon_time == "15:30"
    assert courtesy_time is None


def test_missing_info_message_contains_required_labels():
    from app.api.line import _build_missing_info_message

    text = _build_missing_info_message(["customer_name", "menu_name"])
    assert "お名前" in text
    assert "ご希望メニュー" in text


def test_line_mirror_requires_all_config_values():
    from app.api.line import _line_mirror_is_configured

    with patch("app.api.line.settings.line_mirror_enabled", True), patch(
        "app.api.line.settings.line_mirror_url", "https://staging.example/api/line/mirror-webhook"
    ), patch("app.api.line.settings.line_mirror_shared_secret", "secret"):
        assert _line_mirror_is_configured() is True

    with patch("app.api.line.settings.line_mirror_enabled", False), patch(
        "app.api.line.settings.line_mirror_url", "https://staging.example/api/line/mirror-webhook"
    ), patch("app.api.line.settings.line_mirror_shared_secret", "secret"):
        assert _line_mirror_is_configured() is False


def test_shadow_rule_parse_change_keeps_desired_date_separate_from_current_reservation():
    from app.services.shadow_service import _rule_based_shadow_parse
    from app.utils.datetime_jst import now_jst

    current_year = now_jst().year

    msg = (
        "おはようございます。佐々木です。\n"
        "予約の変更をお願いできますでしょうか？\n"
        "5/2（土）13時に予約を入れて頂いています。\n"
        "翌日5/3（日）はやっていますか？"
    )

    parsed = _rule_based_shadow_parse(msg)

    assert parsed["intent"] == "変更"
    assert parsed["name"] == "佐々木"
    assert parsed["current_date"] == f"{current_year + 1 if now_jst().month > 5 else current_year}-05-02"
    assert parsed["current_time"] == "13:00"
    assert parsed["date"] == f"{current_year + 1 if now_jst().month > 5 else current_year}-05-03"
    assert parsed["time"] is None


@pytest.mark.asyncio
async def test_shadow_existing_reservation_reference_matches_board_by_name_and_time():
    from app.services.shadow_service import _find_existing_reservation_by_reference
    from app.utils.datetime_jst import JST

    patient = SimpleNamespace(id=10, name="佐々木泉美", last_name="佐々木", first_name="泉美")
    practitioner = SimpleNamespace(id=2, name="施術者A")
    menu = SimpleNamespace(id=3, name="保険診療")
    start = datetime(2026, 5, 2, 13, 0, tzinfo=JST)
    reservation = SimpleNamespace(
        id=99,
        patient=patient,
        practitioner=practitioner,
        menu=menu,
        start_time=start,
        end_time=start + timedelta(minutes=60),
    )

    scalar_result = Mock()
    scalar_result.all.return_value = [reservation]
    execute_result = Mock()
    execute_result.scalars.return_value = scalar_result
    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_result)

    matched = await _find_existing_reservation_by_reference(
        db,
        patient_name="佐々木",
        current_date="2026-05-02",
        current_time="13:00",
    )

    assert matched["existing_reservation_id"] == 99
    assert matched["customer_name"] == "佐々木泉美"
    assert matched["practitioner_id"] == 2
    assert matched["practitioner_name"] == "施術者A"
    assert matched["duration_minutes"] == 60
    assert matched["menu_id"] == 3
    assert matched["menu_name"] == "保険診療"


def test_shadow_rule_parse_followup_time_can_complete_existing_change_draft():
    from app.services.shadow_service import _rule_based_shadow_parse

    parsed = _rule_based_shadow_parse("15時〜は大丈夫ですか？")

    assert parsed["time"] == "15:00"
    assert parsed["date"] is None


def test_shadow_manual_without_request_can_restart_on_clear_new_reservation_text():
    from app.services.shadow_service import _should_restart_shadow_from_manual

    msg = "本日空いていますでしょうか。\n腰に加え、先日話した肩首まわりがまだ痛くて..."

    assert _should_restart_shadow_from_manual(msg, {"mode": "manual", "request_id": None, "draft": {}}) is True
    assert _should_restart_shadow_from_manual(msg, {"mode": "manual", "request_id": "rid123", "draft": {}}) is False


def test_shadow_normalize_keeps_availability_with_symptoms_as_reservation_request():
    from app.services.shadow_service import _normalize_analysis

    msg = "本日空いていますでしょうか。\n腰に加え、先日話した肩首まわりがまだ痛くて..."

    parsed = _normalize_analysis({"intent": "相談", "date": None, "time": None}, msg)

    assert parsed["intent"] == "予約希望"
    assert parsed["date"] is not None


def test_shadow_rule_parse_evening_followup_extracts_time():
    from app.services.shadow_service import _rule_based_shadow_parse

    parsed = _rule_based_shadow_parse("夕方頃希望です。")

    assert parsed["time"] == "17:00"
    assert parsed["date"] is None


@pytest.mark.asyncio
async def test_shadow_timetable_patient_uses_shadow_alias_without_line_id():
    from app.api.line import _get_or_create_shadow_timetable_patient

    state = SimpleNamespace(context_data={})
    state_result = Mock()
    state_result.scalar_one_or_none.return_value = state
    existing_scalar = Mock()
    existing_scalar.all.return_value = [SimpleNamespace(name="シャドー1"), SimpleNamespace(name="シャドー3")]
    existing_result = Mock()
    existing_result.scalars.return_value = existing_scalar
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[state_result, existing_result])
    db.flush = AsyncMock()
    created = SimpleNamespace(id=44, name="シャドー4")

    with patch("app.api.line.create_new_patient", new=AsyncMock(return_value=created)) as mock_create:
        patient = await _get_or_create_shadow_timetable_patient(db, "U-real-user")

    assert patient.name == "シャドー4"
    assert state.context_data["shadow_patient_id"] == 44
    assert state.context_data["shadow_patient_name"] == "シャドー4"
    mock_create.assert_awaited_once()
    assert mock_create.await_args.kwargs["name"] == "シャドー4"
    assert mock_create.await_args.kwargs["line_id"] is None


@pytest.mark.asyncio
async def test_shadow_approve_registers_dummy_patient_and_does_not_push_customer():
    from app.api.line import _handle_postback

    start = datetime(2026, 5, 3, 15, 0).astimezone()
    end = start + timedelta(minutes=60)
    req = {
        "user_id": "U-real-customer",
        "customer_name": "実名患者",
        "available": True,
        "practitioner_id": 7,
        "menu_id": None,
        "start_time_iso": start.isoformat(),
        "end_time_iso": end.isoformat(),
        "duration_minutes": 60,
    }
    dummy_patient = SimpleNamespace(id=88, name="シャドー2")
    db = AsyncMock()

    with patch("app.api.line.get_request", new=AsyncMock(return_value=req)), patch(
        "app.api.line._get_or_create_shadow_timetable_patient", new=AsyncMock(return_value=dummy_patient)
    ) as mock_dummy, patch(
        "app.api.line.create_reservation", new=AsyncMock(return_value={"id": 123, "status": "CONFIRMED"})
    ) as mock_create, patch("app.api.line.update_request", new=AsyncMock()), patch(
        "app.api.line.set_user_mode", new=AsyncMock()
    ), patch("app.api.line.push_message", new=AsyncMock()) as mock_push, patch(
        "app.api.line.reply_to_line", new=AsyncMock()
    ), patch("app.api.line.settings.line_admin_user_id", "U-admin"):
        await _handle_postback(
            {"replyToken": "staff-reply", "postback": {"data": "action=shadow_approve&rid=rid123&uid=U-real-customer"}},
            db,
        )

    mock_dummy.assert_awaited_once_with(db, "U-real-customer")
    reservation_data = mock_create.await_args.args[1]
    assert reservation_data.patient_id == 88
    assert "dummy_patient=シャドー2" in reservation_data.notes
    pushed_targets = [call.args[0] for call in mock_push.await_args_list]
    assert pushed_targets == ["U-admin"]


@pytest.mark.asyncio
async def test_shadow_alt_registers_dummy_patient_and_does_not_push_customer():
    from app.api.line import _handle_postback

    req = {
        "user_id": "U-real-customer",
        "customer_name": "実名患者",
        "menu_id": None,
        "alternatives": [
            {
                "date": "2026-05-03",
                "start": "16:00",
                "end": "17:00",
                "practitioner_id": 9,
                "practitioner_name": "施術者A",
            }
        ],
    }
    dummy_patient = SimpleNamespace(id=89, name="シャドー3")
    db = AsyncMock()

    with patch("app.api.line.get_request", new=AsyncMock(return_value=req)), patch(
        "app.api.line._get_or_create_shadow_timetable_patient", new=AsyncMock(return_value=dummy_patient)
    ), patch(
        "app.api.line.create_reservation", new=AsyncMock(return_value={"id": 124, "status": "CONFIRMED"})
    ) as mock_create, patch("app.api.line.update_request", new=AsyncMock()), patch(
        "app.api.line.set_user_mode", new=AsyncMock()
    ), patch("app.api.line.push_message", new=AsyncMock()) as mock_push, patch(
        "app.api.line.reply_to_line", new=AsyncMock()
    ), patch("app.api.line.settings.line_admin_user_id", "U-admin"):
        await _handle_postback(
            {"replyToken": "staff-reply", "postback": {"data": "action=shadow_alt&rid=rid123&alt=1&uid=U-real-customer"}},
            db,
        )

    reservation_data = mock_create.await_args.args[1]
    assert reservation_data.patient_id == 89
    assert "dummy_patient=シャドー3" in reservation_data.notes
    pushed_targets = [call.args[0] for call in mock_push.await_args_list]
    assert pushed_targets == ["U-admin"]


def test_mirror_display_name_includes_environment_label():
    from app.api.line import _mirror_display_name

    event = {
        "source": {"userId": "Uabcdef123456"},
        "_mirror": {"displayName": "山田太郎"},
    }

    assert _mirror_display_name(event, "STAGING-MIRROR") == "[STAGING-MIRROR] 山田太郎"


@pytest.mark.asyncio
async def test_line_mirror_webhook_runs_shadow_handler_with_secret():
    from app.api.line import line_mirror_webhook

    class DummyRequest:
        async def json(self):
            return {
                "mirror": {"label": "STAGING-MIRROR"},
                "events": [
                    {
                        "type": "message",
                        "source": {"userId": "U-customer"},
                        "message": {"type": "text", "text": "明日の10時に予約したいです"},
                        "_mirror": {"displayName": "顧客A"},
                    }
                ],
            }

    db = AsyncMock()
    with patch("app.api.line.settings.line_mirror_shared_secret", "mirror-secret"), patch(
        "app.api.line.handle_shadow_message", new=AsyncMock(return_value=None)
    ) as mock_shadow:
        result = await line_mirror_webhook(DummyRequest(), db, x_line_mirror_secret="mirror-secret")

    assert result == {"status": "ok", "processed": 1, "label": "STAGING-MIRROR"}
    mock_shadow.assert_awaited_once()
    assert mock_shadow.await_args.kwargs["user_id"] == "U-customer"
    assert mock_shadow.await_args.kwargs["text"] == "明日の10時に予約したいです"
    assert mock_shadow.await_args.kwargs["display_name"] == "[STAGING-MIRROR] 顧客A"
    db.commit.assert_awaited_once()


def test_extract_full_name_for_first_time_registration():
    from app.agents.line_parser import extract_full_name

    assert extract_full_name("カルテ用に 田中 太郎 です") == "田中太郎"


def test_autopilot_setup_extracts_name_phone_and_reading_birth_date():
    from app.api.line import _extract_reading_and_birth_date, _extract_setup_name_and_phone

    name, phone = _extract_setup_name_and_phone("斉藤 花子 090-1234-5678", None)
    reading, birth_date = _extract_reading_and_birth_date("さいとう はなこ 1990-04-01")

    assert name == "斉藤花子"
    assert phone == "09012345678"
    assert reading == "さいとう はなこ"
    assert birth_date.isoformat() == "1990-04-01"


def test_autopilot_usual_confirmation_uses_patient_default_menu_duration_and_practitioner():
    from app.api.line import (
        _extract_alternative_choice,
        _format_autopilot_slot_confirmation,
        _format_usual_confirmation,
        _has_vague_time_period,
        _is_affirmative,
        _is_negative,
    )
    from app.utils.datetime_jst import JST

    text = _format_usual_confirmation(
        {
            "menu_name": "マッスルセラピー",
            "duration_minutes": 60,
            "practitioner_name": "時田",
        }
    )

    assert "マッスルセラピー 60分" in text
    assert "担当: 時田" in text
    assert _is_affirmative("はい") is True
    assert _is_affirmative("それでお願いします") is True
    assert _is_affirmative("うん！") is True
    assert _is_affirmative("Yes, please") is True
    assert _is_affirmative("いいよ") is True
    assert _is_affirmative("うん、それでいいよ。明日の午後どう？") is True
    assert _is_affirmative("はい(´Д｀)=3") is True
    assert _is_affirmative("いいえ") is False
    assert _is_negative("いや") is True
    assert _extract_alternative_choice("じゃあ2で！", 3) == 2
    assert _extract_alternative_choice("3番をお願いします", 3) == 3
    assert _extract_alternative_choice("2でお願い", 3) == 2
    assert _extract_alternative_choice("２がいい！", 3) == 2
    assert _extract_alternative_choice("明日の14時", 3) is None
    assert _has_vague_time_period("明日の午後") is True
    assert _has_vague_time_period("明日の14時") is False
    slot_confirmation = _format_autopilot_slot_confirmation(
        datetime(2026, 8, 13, 14, 0, tzinfo=JST),
        datetime(2026, 8, 13, 15, 0, tzinfo=JST),
        "時田",
    )
    assert "8/13(木) 14:00〜15:00" in slot_confirmation
    assert "よろしいでしょうか" in slot_confirmation


def test_compose_alternatives_text_uses_neutral_header_for_vague_time():
    from app.api.line import _compose_alternatives_text

    alternatives = [{"label": "2026-08-13 14:00〜15:00（時田）"}]
    vague = _compose_alternatives_text(alternatives, vague=True)
    full = _compose_alternatives_text(alternatives, vague=False)

    assert "空いているお時間をご案内します" in vague
    assert "埋まって" not in vague
    assert "満席" in full
    # 4つ目の「別日時をどうぞ」メッセージが常に含まれること
    assert "別の日時をお知らせください" in vague
    assert "別の日時をお知らせください" in full


def test_vague_time_window_maps_periods():
    from app.api.line import _vague_time_window

    assert _vague_time_window("明日の午前中") == (0, 12 * 60)
    assert _vague_time_window("午後がいい") == (12 * 60, 24 * 60)
    assert _vague_time_window("夕方で") == (16 * 60, 24 * 60)
    assert _vague_time_window("夜に") == (18 * 60, 24 * 60)
    assert _vague_time_window("お昼ごろ") == (11 * 60, 14 * 60)
    assert _vague_time_window("14時ちょうど") is None


@pytest.mark.asyncio
async def test_extract_requested_practitioner_detects_named_designation():
    from app.api.line import _extract_requested_practitioner

    ueda = SimpleNamespace(id=3, name="上田 花子", is_active=True)
    tokita = SimpleNamespace(id=1, name="時田 太郎", is_active=True)

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return [ueda, tokita]

    class _DB:
        async def execute(self, _q):
            return _Result()

    # 指名の合図あり → 上田を検出
    assert (await _extract_requested_practitioner(_DB(), "担当は上田さんでお願いします")).id == 3
    assert (await _extract_requested_practitioner(_DB(), "上田で")).id == 3
    # 指名の合図なし（本人の名前が偶然一致するだけ）→ 検出しない
    assert await _extract_requested_practitioner(_DB(), "上田と申します") is None
    assert await _extract_requested_practitioner(_DB(), "明日の14時に予約したい") is None


@pytest.mark.asyncio
async def test_autopilot_candidate_selection_books_directly_without_extra_confirmation():
    from app.api.line import _handle_text_message

    patient = SimpleNamespace(id=7, name="時田信", line_autopilot_enabled=True)
    request_data = {
        "menu_id": 5,
        "alternatives": [
            {
                "date": "2026-08-13",
                "start": "14:30",
                "end": "15:30",
                "practitioner_id": 3,
                "practitioner_name": "時田",
                "label": "2026-08-13 14:30〜15:30（時田）",
            }
        ],
    }
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-autopilot"},
        "message": {"type": "text", "text": "1でお願い"},
    }
    db = AsyncMock()

    with patch("app.api.line.settings.line_autopilot_enabled", True), patch(
        "app.api.line.get_user_state",
        new=AsyncMock(return_value={"mode": "adjusting", "draft": {}, "request_id": "rid-1"}),
    ), patch("app.api.line.get_user_mode", new=AsyncMock(return_value="adjusting")), patch(
        "app.api.line._get_line_display_name", new=AsyncMock(return_value="時田")
    ), patch("app.api.line._find_line_patient", new=AsyncMock(return_value=patient)), patch(
        "app.api.line._get_latest_reservation_for_line_user", new=AsyncMock(return_value=None)
    ), patch("app.api.line.get_request", new=AsyncMock(return_value=request_data)), patch(
        "app.api.line.create_notification", new=AsyncMock()
    ), patch(
        "app.api.line.update_request", new=AsyncMock()
    ), patch("app.api.line.create_reservation", new=AsyncMock(return_value={"id": 555, "status": "CONFIRMED"})) as mock_create, patch(
        "app.api.line.clear_user_draft", new=AsyncMock()
    ), patch("app.api.line.set_user_mode", new=AsyncMock()) as mock_set_mode, patch(
        "app.api.line.reply_to_line", new=AsyncMock()
    ) as mock_reply:
        await _handle_text_message(event, db)

    mock_create.assert_awaited_once()
    assert mock_set_mode.await_args.args[2] == "idle"
    assert "ご予約を確定しました" in mock_reply.await_args.args[1]


@pytest.mark.asyncio
async def test_autopilot_cancel_confirmation_accepts_casual_affirmative():
    from app.api.line import _handle_text_message

    patient = SimpleNamespace(id=7, name="時田信", line_autopilot_enabled=True)
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-autopilot"},
        "message": {"type": "text", "text": "うん！"},
    }
    db = AsyncMock()

    with patch("app.api.line.settings.line_autopilot_enabled", True), patch(
        "app.api.line.get_user_state",
        new=AsyncMock(return_value={"mode": "autopilot_cancel_confirm", "draft": {"autopilot_cancel_reservation_id": 91}, "request_id": None}),
    ), patch("app.api.line.get_user_mode", new=AsyncMock(return_value="autopilot_cancel_confirm")), patch(
        "app.api.line._get_line_display_name", new=AsyncMock(return_value="時田")
    ), patch("app.api.line._find_line_patient", new=AsyncMock(return_value=patient)), patch(
        "app.api.line._get_latest_reservation_for_line_user", new=AsyncMock(return_value=None)
    ), patch("app.api.line.create_notification", new=AsyncMock()) as mock_notification, patch(
        "app.api.line.transition_status", new=AsyncMock()
    ) as mock_transition, patch("app.api.line.clear_user_draft", new=AsyncMock()), patch(
        "app.api.line.set_user_mode", new=AsyncMock()
    ) as mock_set_mode, patch("app.api.line.reply_to_line", new=AsyncMock()) as mock_reply:
        await _handle_text_message(event, db)

    mock_transition.assert_awaited_once_with(db, 91, "CANCELLED")
    assert mock_set_mode.await_args.args[2] == "idle"
    assert mock_notification.await_args.args[1] == "reservation_cancelled"
    assert mock_notification.await_args.args[3] == 91
    assert "キャンセルしました" in mock_reply.await_args.args[1]


@pytest.mark.asyncio
async def test_autopilot_change_proposes_slot_before_rescheduling():
    from app.api.line import _complete_autopilot_reschedule
    from app.utils.datetime_jst import JST

    reservation = SimpleNamespace(
        id=91,
        start_time=datetime(2026, 8, 13, 10, 0, tzinfo=JST),
        end_time=datetime(2026, 8, 13, 11, 0, tzinfo=JST),
    )
    practitioner = SimpleNamespace(id=3, name="時田")
    start_dt = datetime(2026, 8, 14, 14, 0, tzinfo=JST)
    end_dt = datetime(2026, 8, 14, 15, 0, tzinfo=JST)
    db = AsyncMock()

    with patch("app.api.line.find_best_practitioner", new=AsyncMock(return_value=(practitioner, start_dt, end_dt, 0, 0))), patch(
        "app.api.line.merge_user_draft", new=AsyncMock()
    ) as mock_merge, patch("app.api.line.set_user_mode", new=AsyncMock()) as mock_set_mode, patch(
        "app.api.line.reply_to_line", new=AsyncMock()
    ) as mock_reply:
        proposed = await _complete_autopilot_reschedule(
            db,
            reservation=reservation,
            desired_date="2026-08-14",
            desired_time="14:00",
            user_id="U-autopilot",
            reply_token="reply-token",
        )

    assert proposed is True
    assert mock_merge.await_args.args[2]["autopilot_change_reservation_id"] == 91
    assert mock_set_mode.await_args.args[2] == "autopilot_change_confirm"
    assert "よろしいでしょうか" in mock_reply.await_args.args[1]


@pytest.mark.asyncio
async def test_autopilot_cancel_failure_replies_and_keeps_confirmation_active():
    from fastapi import HTTPException
    from app.api.line import _handle_text_message

    patient = SimpleNamespace(id=7, name="時田信", line_autopilot_enabled=True)
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-autopilot"},
        "message": {"type": "text", "text": "はい"},
    }
    db = AsyncMock()

    with patch("app.api.line.settings.line_autopilot_enabled", True), patch(
        "app.api.line.get_user_state",
        new=AsyncMock(return_value={"mode": "autopilot_cancel_confirm", "draft": {"autopilot_cancel_reservation_id": 91}, "request_id": None}),
    ), patch("app.api.line.get_user_mode", new=AsyncMock(return_value="autopilot_cancel_confirm")), patch(
        "app.api.line._get_line_display_name", new=AsyncMock(return_value="時田")
    ), patch("app.api.line._find_line_patient", new=AsyncMock(return_value=patient)), patch(
        "app.api.line._get_latest_reservation_for_line_user", new=AsyncMock(return_value=None)
    ), patch("app.api.line.create_notification", new=AsyncMock()), patch(
        "app.api.line.transition_status", new=AsyncMock(side_effect=HTTPException(status_code=400, detail="invalid transition"))
    ), patch("app.api.line.set_user_mode", new=AsyncMock()) as mock_set_mode, patch(
        "app.api.line.reply_to_line", new=AsyncMock()
    ) as mock_reply:
        await _handle_text_message(event, db)

    db.rollback.assert_awaited_once()
    assert mock_set_mode.await_args.args[2] == "autopilot_cancel_confirm"
    assert "完了できませんでした" in mock_reply.await_args.args[1]


@pytest.mark.asyncio
async def test_autopilot_change_without_datetime_asks_and_keeps_conversation_active():
    from app.api.line import _handle_text_message

    patient = SimpleNamespace(id=7, name="時田信", line_autopilot_enabled=True)
    reservation = SimpleNamespace(id=91)
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-autopilot"},
        "message": {"type": "text", "text": "予約変更したい"},
    }
    db = AsyncMock()

    with patch("app.api.line.settings.line_autopilot_enabled", True), patch(
        "app.api.line.get_user_state", new=AsyncMock(return_value={"mode": "idle", "draft": {}, "request_id": None})
    ), patch("app.api.line.get_user_mode", new=AsyncMock(return_value="idle")), patch(
        "app.api.line._get_line_display_name", new=AsyncMock(return_value="時田")
    ), patch("app.api.line._find_line_patient", new=AsyncMock(return_value=patient)), patch(
        "app.api.line._get_latest_reservation_for_line_user", new=AsyncMock(return_value=None)
    ), patch("app.api.line._find_single_upcoming_reservation", new=AsyncMock(return_value=reservation)), patch(
        "app.api.line.parse_line_message", new=AsyncMock(return_value={"date": None, "time": None})
    ), patch("app.api.line.create_notification", new=AsyncMock()), patch(
        "app.api.line.merge_user_draft", new=AsyncMock()
    ) as mock_merge, patch("app.api.line.set_user_mode", new=AsyncMock()) as mock_set_mode, patch(
        "app.api.line.reply_to_line", new=AsyncMock()
    ) as mock_reply:
        await _handle_text_message(event, db)

    assert mock_merge.await_args.args[2]["autopilot_change_reservation_id"] == 91
    assert mock_set_mode.await_args.args[2] == "autopilot_change_datetime"
    assert "変更後の日時" in mock_reply.await_args.args[1]


@pytest.mark.asyncio
async def test_autopilot_setup_keyword_starts_identity_flow_only():
    from app.api.line import _handle_autopilot_setup_message

    db = AsyncMock()
    with patch("app.api.line.clear_user_draft", new=AsyncMock()) as mock_clear, patch(
        "app.api.line.set_user_mode", new=AsyncMock()
    ) as mock_set_mode, patch("app.api.line.reply_to_line", new=AsyncMock()) as mock_reply:
        handled = await _handle_autopilot_setup_message(
            db,
            user_id="U-setup",
            text="#autopilot-setup",
            reply_token="reply-token",
            display_name=None,
            state={"mode": "idle", "draft": {}},
        )

    assert handled is True
    mock_clear.assert_awaited_once_with(db, "U-setup")
    assert mock_set_mode.await_args.args[2] == "autopilot_setup_name_phone"
    assert "COCO整骨院" in mock_reply.await_args.args[1]


@pytest.mark.asyncio
async def test_autopilot_setup_uses_unique_phone_before_reading_birth():
    from app.api.line import _handle_autopilot_setup_message

    db = AsyncMock()
    patient = SimpleNamespace(id=7, name="斉藤花子")
    with patch("app.api.line.merge_user_draft", new=AsyncMock()), patch(
        "app.api.line.find_unique_patient_by_phone", new=AsyncMock(return_value=patient)
    ) as mock_find_phone, patch(
        "app.api.line._complete_autopilot_setup", new=AsyncMock()
    ) as mock_complete:
        handled = await _handle_autopilot_setup_message(
            db,
            user_id="U-setup",
            text="齋藤 花子 090-1234-5678",
            reply_token="reply-token",
            display_name=None,
            state={"mode": "autopilot_setup_name_phone", "draft": {}},
        )

    assert handled is True
    mock_find_phone.assert_awaited_once_with(db, "09012345678")
    mock_complete.assert_awaited_once_with(db, "U-setup", "reply-token", patient)


@pytest.mark.asyncio
async def test_autopilot_setup_asks_reading_and_birth_when_phone_is_not_unique():
    from app.api.line import _handle_autopilot_setup_message

    db = AsyncMock()
    with patch("app.api.line.merge_user_draft", new=AsyncMock()), patch(
        "app.api.line.find_unique_patient_by_phone", new=AsyncMock(return_value=None)
    ), patch("app.api.line.set_user_mode", new=AsyncMock()) as mock_set_mode, patch(
        "app.api.line.reply_to_line", new=AsyncMock()
    ) as mock_reply:
        handled = await _handle_autopilot_setup_message(
            db,
            user_id="U-setup",
            text="斉藤 花子 090-1234-5678",
            reply_token="reply-token",
            display_name=None,
            state={"mode": "autopilot_setup_name_phone", "draft": {}},
        )

    assert handled is True
    assert mock_set_mode.await_args.args[2] == "autopilot_setup_reading_birth"


@pytest.mark.asyncio
async def test_autopilot_rich_menu_trigger_restarts_booking_instead_of_manual_mode():
    from app.api.line import _handle_text_message

    patient = SimpleNamespace(id=7, name="時田信", line_autopilot_enabled=True)
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-autopilot"},
        "message": {"type": "text", "text": "予約/変更"},
    }
    db = AsyncMock()

    with patch("app.api.line.settings.line_autopilot_enabled", True), patch(
        "app.api.line.get_user_state", new=AsyncMock(return_value={"mode": "manual", "draft": {}, "request_id": None})
    ), patch("app.api.line._get_line_display_name", new=AsyncMock(return_value="時田")), patch(
        "app.api.line._find_line_patient", new=AsyncMock(return_value=patient)
    ), patch("app.api.line.create_notification", new=AsyncMock()), patch(
        "app.api.line.clear_user_draft", new=AsyncMock()
    ) as mock_clear, patch("app.api.line.set_user_mode", new=AsyncMock()) as mock_set_mode, patch(
        "app.api.line._build_menu_quick_reply_items", new=AsyncMock(return_value=[])
    ), patch("app.api.line.reply_text_with_quick_reply", new=AsyncMock()) as mock_reply:
        await _handle_text_message(event, db)

    mock_clear.assert_awaited_once_with(db, "U-autopilot")
    assert mock_set_mode.await_args.args[2] == "waiting_menu"
    mock_reply.assert_awaited_once()
    assert "ご希望メニュー" in mock_reply.await_args.args[1]


@pytest.mark.asyncio
async def test_autopilot_natural_booking_message_restarts_from_manual_mode():
    from app.api.line import _handle_text_message

    patient = SimpleNamespace(id=7, name="時田信", line_autopilot_enabled=True)
    event = {
        "replyToken": "reply-token",
        "source": {"userId": "U-autopilot"},
        "message": {"type": "text", "text": "明日の午前中空いてますか？"},
    }
    db = AsyncMock()

    with patch("app.api.line.settings.line_autopilot_enabled", True), patch(
        "app.api.line.get_user_state", new=AsyncMock(return_value={"mode": "manual", "draft": {}, "request_id": None})
    ), patch("app.api.line._get_line_display_name", new=AsyncMock(return_value="時田")), patch(
        "app.api.line._find_line_patient", new=AsyncMock(return_value=patient)
    ), patch("app.api.line.create_notification", new=AsyncMock()), patch(
        "app.api.line.clear_user_draft", new=AsyncMock()
    ), patch("app.api.line.set_user_mode", new=AsyncMock()), patch(
        "app.api.line.get_user_mode", new=AsyncMock(return_value="manual")
    ), patch("app.api.line._get_latest_reservation_for_line_user", new=AsyncMock(return_value=None)), patch(
        "app.api.line.parse_line_message",
        new=AsyncMock(return_value={"has_reservation_intent": True, "date": "2026-08-13", "time": "10:00", "menu_name": None}),
    ), patch(
        "app.api.line.merge_user_draft", new=AsyncMock(return_value={"date": "2026-08-13", "time": "10:00"})
    ), patch(
        "app.api.line._get_patient_default_preset",
        new=AsyncMock(return_value={"menu_name": "マッスルセラピー", "duration_minutes": 60, "practitioner_name": "時田"}),
    ), patch("app.api.line.reply_to_line", new=AsyncMock()) as mock_reply:
        await _handle_text_message(event, db)

    assert "いつものマッスルセラピー 60分" in mock_reply.await_args.args[1]


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


def test_normalize_constraints_converts_llm_objects_to_strings():
    from app.agents.line_parser import _normalize_constraints

    assert _normalize_constraints(
        [
            {"type": "window", "start": "11:00", "end": "14:00"},
            {"type": "symptom", "value": "肩こり"},
            {"asap": True},
            "ref_history",
        ]
    ) == ["window:11:00-14:00", "symptom:肩こり", "asap", "ref_history"]


def test_composer_rejects_reworded_confirmed_facts():
    from app.services.line_composer import _is_grounded_reply

    context = {
        "date": "2026/08/16",
        "start": "14:00",
        "end": "15:00",
        "practitioner": "時田",
        "menu": "保険診療",
    }
    assert _is_grounded_reply(
        "confirmed",
        context,
        "ご予約を確定しました。2026/08/16 14:00〜15:00（担当: 時田・メニュー: 保険診療）",
    )
    assert not _is_grounded_reply(
        "confirmed",
        context,
        "8月16日14時から時田の担当で予約を承りました。",
    )


def test_autopilot_debounce_does_not_merge_thanks_or_changed_intent():
    from app.services.line_debounce import _DEBOUNCE_BUFFER, merge_debounced_message

    _DEBOUNCE_BUFFER.clear()
    assert merge_debounced_message("user-guard", "明日の14時に予約したい") == "明日の14時に予約したい"
    assert merge_debounced_message("user-guard", "ありがとう") == "ありがとう"

    _DEBOUNCE_BUFFER.clear()
    assert merge_debounced_message("user-guard", "明日予約したい") == "明日予約したい"
    assert merge_debounced_message("user-guard", "やっぱりキャンセル") == "やっぱりキャンセル"


@pytest.mark.asyncio
async def test_repeated_autopilot_prompt_hands_off_on_third_attempt():
    from app.api.line import _reply_with_loop_guard

    db = AsyncMock()
    with patch(
        "app.api.line.get_user_state",
        new=AsyncMock(
            return_value={
                "mode": "autopilot_booking_confirm",
                "request_id": "rid-1",
                "draft": {"autopilot_last_situation": "reconfirm_yes_no", "autopilot_situation_streak": 2},
            }
        ),
    ), patch("app.api.line.merge_user_draft", new=AsyncMock()), patch(
        "app.api.line.set_user_mode", new=AsyncMock()
    ) as mock_set_mode, patch("app.api.line.create_notification", new=AsyncMock()), patch(
        "app.api.line._compose_autopilot_reply", new=AsyncMock(return_value="担当者が確認します。")
    ) as mock_compose, patch("app.api.line.reply_to_line", new=AsyncMock()):
        handed_off = await _reply_with_loop_guard(
            db,
            "U-autopilot",
            "reply-token",
            "reconfirm_yes_no",
            {"what": "提示した予約候補", "patient_message": "よく分からない"},
        )

    assert handed_off is True
    mock_set_mode.assert_awaited_once_with(db, "U-autopilot", "manual", "rid-1")
    assert mock_compose.await_args.args[0] == "handoff_to_human"
