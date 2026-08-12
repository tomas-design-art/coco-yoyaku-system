from datetime import date, time, datetime
from types import SimpleNamespace

import pytest

from app.services import slot_scorer
from app.utils.datetime_jst import JST


@pytest.mark.asyncio
async def test_find_best_practitioner_falls_back_when_top_candidate_conflicts(monkeypatch):
    target_date = date(2026, 4, 20)
    start_time = time(10, 0)

    practitioner_conflicted = SimpleNamespace(id=1, name="時田")
    practitioner_available = SimpleNamespace(id=2, name="上田")

    class _ScalarResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return self._items

    class _DB:
        async def execute(self, _query):
            return _ScalarResult([practitioner_conflicted, practitioner_available])

    class _BusinessHours:
        is_open = True

        @staticmethod
        def to_minutes():
            return 600, 1260

    async def fake_get_business_hours_for_date(_db, _target_date):
        return _BusinessHours()

    async def fake_load_day_infos(_db, _target_date, _practitioners):
        return [
            slot_scorer._DayInfo(practitioner_conflicted, True, [], [], 600, 1260),
            slot_scorer._DayInfo(practitioner_available, True, [], [], 600, 1260),
        ]

    async def fake_check_conflict(_db, practitioner_id, start_dt, end_dt):
        assert start_dt == datetime(2026, 4, 20, 10, 0, tzinfo=JST)
        assert end_dt == datetime(2026, 4, 20, 11, 0, tzinfo=JST)
        return [object()] if practitioner_id == 1 else []

    monkeypatch.setattr(slot_scorer, "get_business_hours_for_date", fake_get_business_hours_for_date)
    monkeypatch.setattr(slot_scorer, "_load_day_infos", fake_load_day_infos)
    monkeypatch.setattr(slot_scorer, "check_conflict", fake_check_conflict)

    practitioner, start_dt, end_dt, _, _ = await slot_scorer.find_best_practitioner(
        _DB(),
        target_date,
        start_time,
        60,
    )

    assert practitioner is practitioner_available
    assert start_dt == datetime(2026, 4, 20, 10, 0, tzinfo=JST)
    assert end_dt == datetime(2026, 4, 20, 11, 0, tzinfo=JST)


@pytest.mark.asyncio
async def test_find_best_practitioner_prefers_director(monkeypatch):
    target_date = date(2026, 4, 20)
    start_time = time(10, 0)

    # id=1は施術者、id=2は院長
    practitioner_staff = SimpleNamespace(id=1, name="施術者A", role="施術者", display_order=1)
    practitioner_director = SimpleNamespace(id=2, name="院長B", role="院長", display_order=2)

    class _ScalarResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return self._items

    class _DB:
        async def execute(self, _query):
            return _ScalarResult([practitioner_staff, practitioner_director])

    class _BusinessHours:
        is_open = True

        @staticmethod
        def to_minutes():
            return 600, 1260

    async def fake_get_business_hours_for_date(_db, _target_date):
        return _BusinessHours()

    async def fake_load_day_infos(_db, _target_date, _practitioners):
        return [
            slot_scorer._DayInfo(practitioner_staff, True, [], [], 600, 1260),
            slot_scorer._DayInfo(practitioner_director, True, [], [], 600, 1260),
        ]

    async def fake_check_conflict(_db, practitioner_id, start_dt, end_dt):
        return []

    monkeypatch.setattr(slot_scorer, "get_business_hours_for_date", fake_get_business_hours_for_date)
    monkeypatch.setattr(slot_scorer, "_load_day_infos", fake_load_day_infos)
    monkeypatch.setattr(slot_scorer, "check_conflict", fake_check_conflict)

    # 1) prefer_director=True の場合：院長 (id=2) が選ばれる
    practitioner, _, _, _, _ = await slot_scorer.find_best_practitioner(
        _DB(),
        target_date,
        start_time,
        60,
        prefer_director=True,
    )
    assert practitioner is practitioner_director

    # 2) prefer_director=False の場合：display_orderが若い施術者Aが選ばれる（通常挙動）
    practitioner, _, _, _, _ = await slot_scorer.find_best_practitioner(
        _DB(),
        target_date,
        start_time,
        60,
        prefer_director=False,
    )
    assert practitioner is practitioner_staff


def _make_candidate_db(day_infos):
    class _ScalarResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return self

        def all(self):
            return self._items

    class _DB:
        async def execute(self, _query):
            return _ScalarResult([di.practitioner for di in day_infos])

    class _BusinessHours:
        is_open = True

        @staticmethod
        def to_minutes():
            return 600, 1260  # 10:00〜21:00

    async def fake_bh(_db, _d):
        return _BusinessHours()

    async def fake_load(_db, _d, _pracs):
        return day_infos

    return _DB(), fake_bh, fake_load


@pytest.mark.asyncio
async def test_build_same_day_candidates_prefers_preferred_then_others(monkeypatch):
    """Tier1（希望担当のフル枠）→ Tier3（他担当のフル枠）の順で候補が並ぶ。"""
    target_date = date(2026, 8, 13)
    pref = SimpleNamespace(id=2, name="上田", role="院長", display_order=2)
    other = SimpleNamespace(id=1, name="時田", role="施術者", display_order=1)

    # 上田: 15:00(900)〜21:00(1260)は予約で埋まり、14:00枠だけ空き。時田は終日空き。
    day_infos = [
        slot_scorer._DayInfo(other, True, [], [], 600, 1260),
        slot_scorer._DayInfo(pref, True, [(900, 1260)], [], 600, 1260),
    ]
    db, fake_bh, fake_load = _make_candidate_db(day_infos)
    monkeypatch.setattr(slot_scorer, "get_business_hours_for_date", fake_bh)
    monkeypatch.setattr(slot_scorer, "_load_day_infos", fake_load)

    results = await slot_scorer.build_same_day_candidates(
        db, target_date, time(14, 0), 60, preferred_practitioner_id=2, max_results=3,
    )

    assert len(results) == 2
    # 1件目は希望担当（上田）の14:00フル枠
    assert results[0].practitioner_id == 2
    assert "14:00〜15:00" in results[0].label
    assert "担当:上田" in results[0].label
    # 2件目は他担当（時田）のフル枠
    assert results[1].practitioner_id == 1
    assert "担当:時田" in results[1].label


@pytest.mark.asyncio
async def test_build_same_day_candidates_offers_short_gap_slot(monkeypatch):
    """希望担当にフル枠が無くても、min_gap以上の短い空き（Tier2）を提示する。"""
    target_date = date(2026, 8, 13)
    pref = SimpleNamespace(id=2, name="上田", role="院長", display_order=2)
    other = SimpleNamespace(id=1, name="時田", role="施術者", display_order=1)

    # 上田: 10:00-14:00 と 14:40-21:00 が予約 → 14:00〜14:40 の40分だけ空き。
    day_infos = [
        slot_scorer._DayInfo(other, True, [], [], 600, 1260),
        slot_scorer._DayInfo(pref, True, [(600, 840), (880, 1260)], [], 600, 1260),
    ]
    db, fake_bh, fake_load = _make_candidate_db(day_infos)
    monkeypatch.setattr(slot_scorer, "get_business_hours_for_date", fake_bh)
    monkeypatch.setattr(slot_scorer, "_load_day_infos", fake_load)

    results = await slot_scorer.build_same_day_candidates(
        db, target_date, time(14, 0), 60, preferred_practitioner_id=2, max_results=3,
    )

    # 1件目は上田の40分枠（フル未満なので「分」表記が入る）
    assert results[0].practitioner_id == 2
    assert "40分" in results[0].label
    assert "14:00〜14:40" in results[0].label
