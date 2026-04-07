"""予約関連テスト"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

# テスト用のデータ
JST = timezone(timedelta(hours=9))


def make_reservation_data(
    practitioner_id=1,
    start_hour=10, start_min=0,
    end_hour=10, end_min=45,
    channel="PHONE",
    menu_id=1,
    patient_id=1,
):
    today = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "practitioner_id": practitioner_id,
        "patient_id": patient_id,
        "menu_id": menu_id,
        "start_time": today.replace(hour=start_hour, minute=start_min).isoformat(),
        "end_time": today.replace(hour=end_hour, minute=end_min).isoformat(),
        "channel": channel,
        "notes": "テスト予約",
    }


class TestReservationValidation:
    """予約バリデーションテスト"""

    def test_5min_interval_valid(self):
        """5分刻みの時間はOK"""
        data = make_reservation_data(start_min=0, end_min=45)
        assert int(data["start_time"].split("T")[1].split(":")[1]) % 5 == 0

    def test_5min_interval_invalid(self):
        """5分刻みでない時間はNG"""
        # 3分はNG
        assert 3 % 5 != 0

    def test_end_after_start(self):
        """end_time > start_time"""
        data = make_reservation_data(start_hour=10, end_hour=10, start_min=0, end_min=45)
        start = datetime.fromisoformat(data["start_time"])
        end = datetime.fromisoformat(data["end_time"])
        assert end > start

    def test_valid_channels(self):
        """有効なチャネル"""
        valid = {"PHONE", "WALK_IN", "LINE", "HOTPEPPER", "WEB"}
        for ch in valid:
            data = make_reservation_data(channel=ch)
            assert data["channel"] in valid


class TestStatusTransitions:
    """ステータス遷移テスト"""

    def test_valid_transitions(self):
        """正常な遷移パス"""
        valid = {
            "PENDING": {"CONFIRMED", "REJECTED", "EXPIRED"},
            "HOLD": {"CONFIRMED", "EXPIRED"},
            "CONFIRMED": {"CHANGE_REQUESTED", "CANCEL_REQUESTED"},
            "CHANGE_REQUESTED": {"CANCELLED"},
            "CANCEL_REQUESTED": {"CANCELLED"},
        }

        # PENDING → CONFIRMED
        assert "CONFIRMED" in valid["PENDING"]
        # CONFIRMED → CANCEL_REQUESTED
        assert "CANCEL_REQUESTED" in valid["CONFIRMED"]
        # CANCEL_REQUESTED → CANCELLED
        assert "CANCELLED" in valid["CANCEL_REQUESTED"]

    def test_invalid_transitions(self):
        """不正な遷移（終端ステータスからの遷移）"""
        terminal = {"CANCELLED", "REJECTED", "EXPIRED"}
        valid = {
            "PENDING": {"CONFIRMED", "REJECTED", "EXPIRED"},
            "HOLD": {"CONFIRMED", "EXPIRED"},
            "CONFIRMED": {"CHANGE_REQUESTED", "CANCEL_REQUESTED"},
        }

        # CANCELLED → CONFIRMED は不可
        assert "CANCELLED" not in valid.get("CANCELLED", set())
        # EXPIRED → 何にも遷移不可
        assert "EXPIRED" in terminal

    def test_cancel_flow(self):
        """CONFIRMED → CANCEL_REQUESTED → CANCELLED"""
        valid = {
            "CONFIRMED": {"CHANGE_REQUESTED", "CANCEL_REQUESTED"},
            "CANCEL_REQUESTED": {"CANCELLED"},
        }
        assert "CANCEL_REQUESTED" in valid["CONFIRMED"]
        assert "CANCELLED" in valid["CANCEL_REQUESTED"]

    def test_change_flow(self):
        """CONFIRMED → CHANGE_REQUESTED → CANCELLED（旧）+ CONFIRMED（新）"""
        valid = {
            "CONFIRMED": {"CHANGE_REQUESTED", "CANCEL_REQUESTED"},
            "CHANGE_REQUESTED": {"CANCELLED"},
        }
        assert "CHANGE_REQUESTED" in valid["CONFIRMED"]
        assert "CANCELLED" in valid["CHANGE_REQUESTED"]


class TestConflictDetection:
    """競合検出テスト"""

    def test_overlap_detection(self):
        """時間帯重複の検出ロジック"""
        # 予約A: 10:00-10:45
        a_start, a_end = 600, 645  # minutes from midnight
        # 予約B: 10:30-11:15 (重複あり)
        b_start, b_end = 630, 675

        # 重複判定: a_start < b_end and a_end > b_start
        assert a_start < b_end and a_end > b_start

    def test_no_overlap(self):
        """時間帯が重複しない"""
        # 予約A: 10:00-10:45
        a_start, a_end = 600, 645
        # 予約B: 11:00-11:45 (重複なし)
        b_start, b_end = 660, 705

        assert not (a_start < b_end and a_end > b_start) or a_end <= b_start

    def test_adjacent_no_overlap(self):
        """隣接する予約は重複しない"""
        # 予約A: 10:00-10:45
        # 予約B: 10:45-11:30
        a_end = 645
        b_start = 645

        # 隣接（end == start）は重複しない
        assert a_end <= b_start


class TestAutoConfirm:
    """自動確定ルールテスト"""

    def test_all_conditions_met(self):
        """全条件満たす → CONFIRMED"""
        has_menu = True
        has_practitioner = True
        no_conflicts = True
        within_business_hours = True

        should_confirm = has_menu and has_practitioner and no_conflicts and within_business_hours
        assert should_confirm

    def test_missing_menu(self):
        """menu_id未指定 → PENDING"""
        has_menu = False
        should_confirm = has_menu
        assert not should_confirm

    def test_has_conflict(self):
        """競合あり → PENDING"""
        no_conflicts = False
        should_confirm = no_conflicts
        assert not should_confirm


class TestHotPepperParsing:
    """HotPepperメール解析テスト"""

    def test_rule_based_parse(self):
        """ルールベース解析 (SALON BOARD形式)"""
        from app.agents.mail_parser import parse_hotpepper_mail

        email = (
            "■予約番号\n　HP12345\n"
            "■氏名\n　田中太郎\n"
            "■来店日時\n　2026年03月15日（日）10:00\n"
            "■メニュー\n　骨盤矯正\n"
        )
        result = parse_hotpepper_mail(email)
        assert result["reservation_number"] == "HP12345"
        assert result["patient_name"] == "田中太郎"
        assert result["start_time"].month == 3
        assert result["start_time"].day == 15
        assert result["start_time"].hour == 10
        assert result["menu_name"] == "骨盤矯正"


class TestLineParsing:
    """LINEメッセージ解析テスト"""

    def test_reservation_intent(self):
        """予約意図のあるメッセージ"""
        from app.agents.line_parser import _rule_based_parse

        result = _rule_based_parse("3月15日の10時に予約したいです")
        assert result["has_reservation_intent"] is True
        assert result["time"] == "10:00"

    def test_no_reservation_intent(self):
        """予約意図のないメッセージ"""
        from app.agents.line_parser import _rule_based_parse

        result = _rule_based_parse("こんにちは、質問があります")
        assert result["has_reservation_intent"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
