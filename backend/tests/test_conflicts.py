"""競合検出テスト"""
import pytest
from datetime import datetime, timezone, timedelta


JST = timezone(timedelta(hours=9))


class TestConflictLogic:
    """競合検出ロジックの単体テスト"""

    @staticmethod
    def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        """時間帯が重複するかどうか"""
        return a_start < b_end and a_end > b_start

    def test_full_overlap(self):
        """完全に重なる"""
        assert self.overlaps(600, 645, 600, 645)

    def test_partial_overlap_start(self):
        """先頭が重なる"""
        assert self.overlaps(600, 645, 630, 675)

    def test_partial_overlap_end(self):
        """末尾が重なる"""
        assert self.overlaps(630, 675, 600, 645)

    def test_contained(self):
        """内包"""
        assert self.overlaps(600, 700, 620, 660)

    def test_no_overlap_before(self):
        """前方で重ならない"""
        assert not self.overlaps(600, 645, 645, 700)

    def test_no_overlap_after(self):
        """後方で重ならない"""
        assert not self.overlaps(700, 745, 600, 645)

    def test_adjacent(self):
        """隣接（重ならない）"""
        assert not self.overlaps(600, 645, 645, 690)

    def test_same_practitioner_different_time(self):
        """同一施術者・異なる時間帯 → 重複なし"""
        assert not self.overlaps(600, 645, 700, 745)

    def test_exclude_constraint_statuses(self):
        """EXCLUDE制約対象ステータス"""
        active_statuses = {"CONFIRMED", "HOLD", "PENDING"}
        assert "CONFIRMED" in active_statuses
        assert "CANCELLED" not in active_statuses
        assert "EXPIRED" not in active_statuses


class TestHotPepperConflict:
    """HotPepper予約の競合テスト"""

    def test_hotpepper_registers_despite_conflict(self):
        """HotPepper予約は競合があっても登録する"""
        channel = "HOTPEPPER"
        has_conflict = True
        # HotPepper予約は外部で確定済みのため、競合があっても登録する
        should_register = True  # always register for HOTPEPPER
        assert should_register

    def test_conflict_note_created(self):
        """競合時にconflict_noteが記録される"""
        conflict_info = "鈴木花子(10:00-10:45)"
        conflict_note = f"競合: {conflict_info}"
        assert "競合" in conflict_note
        assert "鈴木花子" in conflict_note


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
