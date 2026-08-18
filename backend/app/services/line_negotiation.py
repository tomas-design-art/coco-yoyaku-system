"""LINE autopilot の constraints を空き枠検索の条件へ変換する。

候補提示後の条件変更（交渉）も、キーワード分岐ではなく constraints 経由で扱う。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

_WEEKDAY_CODES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")


def _to_minutes(value: str) -> int | None:
    match = _TIME_PATTERN.match(value.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 24 or minute > 59:
        return None
    return hour * 60 + minute


@dataclass
class SlotFilters:
    """空き枠検索へ渡せる形に正規化した希望条件。"""

    window_start_min: int | None = None
    window_end_min: int | None = None
    exclude_dates: set[str] = field(default_factory=set)
    exclude_weekdays: set[int] = field(default_factory=set)
    asap: bool = False
    earlier: bool = False
    later: bool = False
    duration_flexible: bool = False

    @property
    def has_condition(self) -> bool:
        return any(
            [
                self.window_start_min is not None,
                self.window_end_min is not None,
                self.exclude_dates,
                self.exclude_weekdays,
                self.asap,
                self.earlier,
                self.later,
                self.duration_flexible,
            ]
        )

    def allows_date(self, target: date) -> bool:
        return (
            target.isoformat() not in self.exclude_dates
            and target.weekday() not in self.exclude_weekdays
        )

    def narrow_start(self, minute: int | None) -> None:
        if minute is None:
            return
        self.window_start_min = minute if self.window_start_min is None else max(self.window_start_min, minute)

    def narrow_end(self, minute: int | None) -> None:
        if minute is None:
            return
        self.window_end_min = minute if self.window_end_min is None else min(self.window_end_min, minute)

    def merge(self, other: "SlotFilters") -> "SlotFilters":
        """新しい希望（other）を優先しつつ、既存条件を引き継ぐ。"""
        merged = SlotFilters(
            window_start_min=self.window_start_min,
            window_end_min=self.window_end_min,
            exclude_dates=set(self.exclude_dates),
            exclude_weekdays=set(self.exclude_weekdays),
            asap=self.asap or other.asap,
            earlier=other.earlier,
            later=other.later,
            duration_flexible=self.duration_flexible or other.duration_flexible,
        )
        # 時間帯の指定し直しは上書き（狭め続けて空にしないため）
        if other.window_start_min is not None or other.window_end_min is not None:
            merged.window_start_min = other.window_start_min
            merged.window_end_min = other.window_end_min
        merged.exclude_dates |= other.exclude_dates
        merged.exclude_weekdays |= other.exclude_weekdays
        return merged

    def to_dict(self) -> dict:
        return {
            "window_start_min": self.window_start_min,
            "window_end_min": self.window_end_min,
            "exclude_dates": sorted(self.exclude_dates),
            "exclude_weekdays": sorted(self.exclude_weekdays),
            "asap": self.asap,
            "duration_flexible": self.duration_flexible,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "SlotFilters":
        data = data or {}
        return cls(
            window_start_min=data.get("window_start_min"),
            window_end_min=data.get("window_end_min"),
            exclude_dates=set(data.get("exclude_dates") or []),
            exclude_weekdays=set(data.get("exclude_weekdays") or []),
            asap=bool(data.get("asap")),
            duration_flexible=bool(data.get("duration_flexible")),
        )


def build_slot_filters(constraints: list[str] | None) -> SlotFilters:
    """parser が返した constraints を検索条件へ変換する。"""
    filters = SlotFilters()
    for raw in constraints or []:
        if not isinstance(raw, str):
            continue
        item = raw.strip()
        key, _, value = item.partition(":")
        key = key.strip()
        value = value.strip()

        if key == "window":
            start, _, end = value.partition("-")
            start_min = _to_minutes(start)
            end_min = _to_minutes(end)
            if start_min is not None and end_min is not None and start_min < end_min:
                filters.window_start_min = start_min
                filters.window_end_min = end_min
        elif key == "after":
            filters.narrow_start(_to_minutes(value))
        elif key in {"before", "end_by"}:
            filters.narrow_end(_to_minutes(value))
        elif key == "exclude_weekday":
            weekday = _WEEKDAY_CODES.get(value.lower())
            if weekday is not None:
                filters.exclude_weekdays.add(weekday)
        elif key == "exclude_date":
            try:
                filters.exclude_dates.add(date.fromisoformat(value).isoformat())
            except ValueError:
                continue
        elif item == "asap":
            filters.asap = True
        elif item == "earlier":
            filters.earlier = True
        elif item == "later":
            filters.later = True
        elif item == "duration_flexible":
            filters.duration_flexible = True

    if filters.window_start_min is not None and filters.window_end_min is not None:
        if filters.window_start_min >= filters.window_end_min:
            filters.window_start_min = None
            filters.window_end_min = None
    return filters


def detect_condition_change(parsed: dict | None) -> SlotFilters | None:
    """候補提示後のメッセージが条件変更かどうかを判定し、検索条件を返す。"""
    parsed = parsed or {}
    filters = build_slot_filters(parsed.get("constraints"))
    if filters.has_condition or parsed.get("date") or parsed.get("time"):
        return filters
    return None
