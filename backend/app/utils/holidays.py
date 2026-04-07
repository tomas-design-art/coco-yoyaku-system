"""日本の祝日判定ユーティリティ"""
from datetime import date
from functools import lru_cache

import holidays


@lru_cache(maxsize=8)
def _jp_holidays(year: int) -> holidays.Japan:
    return holidays.Japan(years=year)


def is_japanese_holiday(d: date) -> bool:
    """指定日が日本の祝日かどうかを返す"""
    return d in _jp_holidays(d.year)


def get_holiday_name(d: date) -> str | None:
    """祝日名を返す。祝日でなければ None"""
    jp = _jp_holidays(d.year)
    return jp.get(d)
