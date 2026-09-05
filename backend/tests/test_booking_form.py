"""予約フォーム（埋めるべき箱）の定義そのものを固定するテスト。

2026-09-04 の実機テストで、担当者の指名が何度言われても届かず、
取消の確認に再予約の話が混ざって取消が実行されない事故が起きた。
原因はどちらも「箱が決まっていなかった」こと。ここが唯一の定義。
"""
from __future__ import annotations

from app.services.booking_form import (
    CANCEL_SLOTS,
    INFERRED,
    PATIENT,
    PRESET,
    Form,
)


def test_booking_requires_datetime_duration_menu_and_practitioner():
    """予約はこの箱が全部埋まるまで確定しない。"""
    form = Form.booking({})
    assert [slot.key for slot in form.missing()] == [
        "date",
        "time",
        "menu_id",
        "duration_minutes",
        "practitioner_id",
    ]
    assert form.is_complete() is False
    assert form.can_commit() is False


def test_slots_can_be_filled_in_any_order():
    """埋まる順番は患者次第。順序を固定したフローでは書けない。"""
    from_date = Form.booking({})
    from_date.fill("date", "2026-09-06").fill("time", "15:00")
    assert [slot.key for slot in from_date.missing()] == [
        "menu_id",
        "duration_minutes",
        "practitioner_id",
    ]
    assert from_date.next_group() == "施術内容"

    # 「いつもの」は3つ同時に埋まり、残るのは日時だけになる
    from_usual = Form.booking({})
    from_usual.fill("menu_id", 5).fill("duration_minutes", 60).fill("practitioner_id", 1)
    assert [slot.key for slot in from_usual.missing()] == ["date", "time"]
    assert from_usual.next_group() == "希望日時"
    assert from_usual.next_question_labels() == ["ご希望日", "ご希望のお時間"]


def test_a_filled_slot_is_never_cleared_by_an_empty_value():
    """埋まった箱は捨てない。捨てると患者は毎回ゼロからやり直しになる。"""
    form = Form.booking({}).fill("practitioner_id", 1)
    form.fill("practitioner_id", None).fill("practitioner_id", "")
    assert form.value("practitioner_id") == 1


def test_values_the_patient_did_not_say_need_approval_before_committing():
    """登録情報から補った値のまま確定しない（「勝手に決められた」を防ぐ）。"""
    form = Form.booking({})
    form.fill("date", "2026-09-06").fill("time", "15:00")
    form.fill("menu_id", 5, PRESET).fill("duration_minutes", 60, PRESET)
    form.fill("practitioner_id", 1, INFERRED)

    assert form.is_complete() is True
    assert form.needs_confirmation() is True
    assert form.can_commit() is False
    assert {slot.key for slot in form.unapproved()} == {
        "menu_id",
        "duration_minutes",
        "practitioner_id",
    }

    # 患者が確認したら、述べられた値と同じ扱いになる
    form.approve()
    assert form.needs_confirmation() is False
    assert form.can_commit() is True


def test_values_the_patient_said_can_be_committed_directly():
    form = Form.booking({})
    for key, value in (
        ("date", "2026-09-06"),
        ("time", "15:00"),
        ("menu_id", 5),
        ("duration_minutes", 60),
        ("practitioner_id", 1),
    ):
        form.fill(key, value, PATIENT)
    assert form.can_commit() is True


def test_existing_conversation_state_maps_onto_the_form():
    """いまの draft をそのまま読める（移行を一度に済ませないための橋渡し）。"""
    draft = {
        "date": "2026-09-06",
        "time": "15:00",
        "menu_id": 5,
        "menu_name": "マッスルセラピー",
        "duration_minutes": 60,
        "practitioner_id": 1,
        # 「いつもの」から補った印
        "assumed_menu": "マッスルセラピー",
        "assumed_practitioner": "時田",
    }
    form = Form.booking(draft)
    assert form.is_complete() is True
    assert form.source("date") == PATIENT
    assert form.source("menu_id") == PRESET
    assert form.source("practitioner_id") == PRESET
    assert form.source("duration_minutes") == PATIENT
    assert form.can_commit() is False


def test_change_form_starts_from_the_reservation_being_changed():
    form = Form.change({})
    assert [slot.key for slot in form.missing()][0] == "target_reservation_id"

    form = Form.change({"autopilot_change_reservation_id": 2536})
    assert form.value("target_reservation_id") == 2536
    assert [slot.key for slot in form.missing()] == ["date", "time"]


def test_cancel_form_only_needs_the_target_reservation():
    form = Form.cancel({})
    assert [slot.key for slot in form.missing()] == ["target_reservation_id"]

    form = Form.cancel({"autopilot_cancel_reservation_id": 2536})
    assert form.is_complete() is True
    assert form.can_commit() is True


def test_cancel_form_has_no_rebooking_slot():
    """★取消フォームに再予約の箱を作らない。

    2026-09-04 実機: 取消の確認に「改めて別の日程でご予約をお取りしましょうか？」が
    混ざり、患者の「いいえ」がどちらへの答えか分からなくなって取消が実行されなかった。
    箱が無ければ混ざらない。
    """
    keys = {slot.key for slot in CANCEL_SLOTS}
    assert keys == {"target_reservation_id"}
    for forbidden in ("date", "time", "menu_id", "duration_minutes", "practitioner_id"):
        assert forbidden not in keys
