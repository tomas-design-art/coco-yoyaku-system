"""予約・変更・取消それぞれで「埋めるべき箱」を1箇所に定義する。

予約システム本体は ReservationCreate(practitioner_id, menu_id, start_time, end_time)
と、埋める箱が型で決まっている。LINE側にはそれが無く、会話のモードごとに
埋め方の分岐が散らばっていた。そのため会話が進むほどスロットが更新されなくなり、
担当者の指名が何度言われても届かない状態になっていた（2026-09-04 実機）。

ここが唯一の定義。「次に何を聞くか」はモードで分岐せず、空いている箱から決める。

設計の要点は3つ。

1. 箱は値だけでなく **出どころ** を持つ。
   患者が述べた値はそのまま確定してよいが、登録情報から補った値や推測した値は
   患者の承認を取るまで確定してはいけない。ここを区別しないと
   「勝手に決められた」事故になる。

2. **フォームは混ぜない。**
   取消フォームには再予約の箱が存在しない。取消の確認と再予約の提案を
   同じやり取りに混ぜたことで、患者の「いいえ」がどちらへの答えか分からなくなり、
   取消が実行されなかった（2026-09-04 実機）。混ざらない形にしておく。

3. 埋める順番は決めない。
   「明日予約したい」から始まる人もいれば「いつもの」から始まる人もいる。
   「いつもの」はメニュー・施術時間・担当を同時に埋める。順序を固定した
   フローでは書けないので、空いている箱を見て次を決める。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# 値の出どころ。確定してよいのは PATIENT だけ。
PATIENT = "patient"      # 患者が述べた
PRESET = "preset"        # 登録情報（いつもの・前回）から補った
INFERRED = "inferred"    # システムが推測した

NEEDS_APPROVAL = frozenset({PRESET, INFERRED})


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    #  会話上まとめて尋ねる単位（日付と時刻は「ご希望日時」として一緒に聞く）
    group: str
    # 既存の会話状態(draft)での保存名。移行が済むまでの橋渡し。
    draft_key: str | None = None

    @property
    def storage_key(self) -> str:
        return self.draft_key or self.key


BOOKING_SLOTS: tuple[Slot, ...] = (
    Slot("date", "ご希望日", "希望日時"),
    Slot("time", "ご希望のお時間", "希望日時"),
    Slot("menu_id", "メニュー", "施術内容"),
    Slot("duration_minutes", "施術時間", "施術内容"),
    Slot("practitioner_id", "担当者", "担当者"),
)

CHANGE_SLOTS: tuple[Slot, ...] = (
    Slot("target_reservation_id", "変更するご予約", "対象", "autopilot_change_reservation_id"),
    Slot("date", "変更後のご希望日", "希望日時"),
    Slot("time", "変更後のご希望のお時間", "希望日時"),
)

# ★取消フォームに再予約の箱は無い。ここに足してはいけない。
#   取消が完了してから、別のフォームとして予約を始める。
CANCEL_SLOTS: tuple[Slot, ...] = (
    Slot("target_reservation_id", "キャンセルするご予約", "対象", "autopilot_cancel_reservation_id"),
)

# draft に置かれている「この値は患者が述べたものではない」という印。
_ASSUMED_KEYS = {
    "menu_id": "assumed_menu",
    "duration_minutes": "assumed_duration",
    "practitioner_id": "assumed_practitioner",
    "date": "assumed_date",
    "time": "assumed_time",
}


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


@dataclass
class Form:
    """1つのやり取りで埋めるべき箱の集合。"""

    name: str
    slots: tuple[Slot, ...]
    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    # ── 参照 ────────────────────────────────────────────
    def value(self, key: str) -> Any:
        return self.values.get(key)

    def source(self, key: str) -> str | None:
        return self.sources.get(key) if self.is_filled(key) else None

    def is_filled(self, key: str) -> bool:
        return not _is_empty(self.values.get(key))

    def missing(self) -> list[Slot]:
        """まだ埋まっていない箱。定義順。"""
        return [slot for slot in self.slots if not self.is_filled(slot.key)]

    def unapproved(self) -> list[Slot]:
        """埋まってはいるが、患者が述べたものではない箱。"""
        return [
            slot
            for slot in self.slots
            if self.is_filled(slot.key) and self.sources.get(slot.key) in NEEDS_APPROVAL
        ]

    def is_complete(self) -> bool:
        return not self.missing()

    def needs_confirmation(self) -> bool:
        """このまま確定してよいか。補った値が残っていれば確認が要る。"""
        return bool(self.unapproved())

    def can_commit(self) -> bool:
        return self.is_complete() and not self.needs_confirmation()

    # ── 次に聞くこと ─────────────────────────────────────
    def next_group(self) -> str | None:
        """次に尋ねるべき塊。空いている箱の並び順で決める（モードでは決めない）。"""
        missing = self.missing()
        return missing[0].group if missing else None

    def next_question_labels(self) -> list[str]:
        """次に尋ねる塊に含まれる、空いている箱の名前。"""
        group = self.next_group()
        if group is None:
            return []
        return [slot.label for slot in self.missing() if slot.group == group]

    # ── 更新 ────────────────────────────────────────────
    def fill(self, key: str, value: Any, source: str = PATIENT) -> "Form":
        """箱を埋める。空の値では上書きしない（埋まった箱は捨てない）。"""
        if _is_empty(value):
            return self
        self.values[key] = value
        self.sources[key] = source
        return self

    def approve(self, keys: Iterable[str] | None = None) -> "Form":
        """患者が確認した箱を、述べられた値と同じ扱いにする。"""
        targets = list(keys) if keys is not None else [slot.key for slot in self.slots]
        for key in targets:
            if self.is_filled(key):
                self.sources[key] = PATIENT
        return self

    # ── 既存の draft との橋渡し ────────────────────────────
    @classmethod
    def from_draft(cls, name: str, slots: tuple[Slot, ...], draft: dict | None) -> "Form":
        draft = draft or {}
        values: dict[str, Any] = {}
        sources: dict[str, str] = {}
        for slot in slots:
            value = draft.get(slot.storage_key)
            if _is_empty(value):
                continue
            values[slot.key] = value
            assumed_key = _ASSUMED_KEYS.get(slot.key)
            sources[slot.key] = (
                PRESET if assumed_key and draft.get(assumed_key) else PATIENT
            )
        return cls(name=name, slots=slots, values=values, sources=sources)

    @classmethod
    def booking(cls, draft: dict | None = None) -> "Form":
        return cls.from_draft("booking", BOOKING_SLOTS, draft)

    @classmethod
    def change(cls, draft: dict | None = None) -> "Form":
        return cls.from_draft("change", CHANGE_SLOTS, draft)

    @classmethod
    def cancel(cls, draft: dict | None = None) -> "Form":
        return cls.from_draft("cancel", CANCEL_SLOTS, draft)
