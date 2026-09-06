"""返信の骨格とその契約。

これまでは LLM が全文を書き、コードが後から場面ごとの規則で検査していた。
穴を1つ塞ぐたびに LLM は別の言い方で同じことをするため、規則が増え続けていた
（2026-09-04〜09-06 の実機で3回起きた）。

ここでは向きが逆になっている。コードが骨格を決め、LLM は言い回しだけを整える。
検査する内容は骨格そのものから決まるので、場面ごとの規則を足す必要がない。
"""
from __future__ import annotations

import pytest

from app.services.reply_plan import ReplyPlan


def _cancel_confirmation() -> ReplyPlan:
    return ReplyPlan(
        facts=["2026/09/06 15:00からのご予約（担当: 時田）"],
        ask="こちらのご予約をキャンセルしてよろしいですか？",
        ask_about="キャンセル",
        yes_no=True,
        keep=["2026/09/06", "15:00", "時田"],
    )


def test_the_skeleton_is_a_message_that_can_be_sent_as_is():
    """LLMが使えなくても会話が止まらないこと。"""
    rendered = _cancel_confirmation().render()
    assert "2026/09/06 15:00からのご予約（担当: 時田）" in rendered
    assert "キャンセルしてよろしいですか？" in rendered
    assert rendered.endswith("はい / いいえ")


def test_a_reworded_skeleton_is_accepted():
    """言い回しを整えただけなら通す。ここを止めると機械的な文面に戻ってしまう。"""
    polished = (
        "2026/09/06 15:00からのご予約（担当: 時田）ですね。\n"
        "こちらのご予約をキャンセルしてよろしいでしょうか？\n"
        "はい / いいえ"
    )
    assert _cancel_confirmation().rejects(polished) is None


@pytest.mark.parametrize(
    "polished,expected",
    [
        # 実機で起きた事故そのもの：質問が別の話へ差し替わり、「いいえ」の意味が反転した
        (
            "2026/09/06 15:00（担当: 時田）のキャンセルを承ります。\n"
            "改めて別の日程でご予約をお取りしましょうか？\nはい / いいえ",
            "質問が別の話",
        ),
        # 質問を足す
        (
            "2026/09/06 15:00（担当: 時田）をキャンセルしてよろしいですか？\n"
            "別の日程もお取りしましょうか？\nはい / いいえ",
            "質問が増えている",
        ),
        # 確定事実を落とす
        ("ご予約をキャンセルしてよろしいですか？\nはい / いいえ", "確定事実が消えている"),
        # はい/いいえの案内を落とす
        ("2026/09/06 15:00（担当: 時田）のご予約をキャンセルしますね。", "「はい/いいえ」の案内"),
        # 実行していない完了を伝える
        (
            "2026/09/06 15:00（担当: 時田）でご予約を承りました。\n"
            "キャンセルしてよろしいですか？\nはい / いいえ",
            "骨格に無い完了",
        ),
        ("", "空の返信"),
    ],
)
def test_a_polished_reply_that_breaks_the_skeleton_is_rejected(polished, expected):
    reason = _cancel_confirmation().rejects(polished)
    assert reason is not None
    assert expected in reason


def test_a_plan_without_a_question_must_not_be_turned_into_one():
    """聞いていない場面で「はい/いいえ」を作らせない。

    2026-09-06 実機: 確認を受け付けられないのに確認文を出し、
    患者の「はい」に「うまく聞き取れず申し訳ありません」と返した。
    """
    plan = ReplyPlan(
        facts=["2026/09/06 15:00のご予約をキャンセルしました。"],
        keep=["2026/09/06", "15:00"],
    )
    assert plan.rejects("2026/09/06 15:00のご予約をキャンセルしました。") is None
    assert "はい/いいえ" in (
        plan.rejects("2026/09/06 15:00のご予約をキャンセルしました。\n続けて予約しますか？\nはい / いいえ") or ""
    )
    assert "質問が増えている" in (
        plan.rejects("2026/09/06 15:00のご予約をキャンセルしました。\n別の日程をお取りしましょうか？") or ""
    )


def test_numbered_options_keep_their_numbers():
    plan = ReplyPlan(
        facts=["9/6(日) の空き状況です。"],
        options=["17:00〜18:00（担当: 出口）", "18:00〜19:00（担当: 出口）"],
        ask="ご希望の番号を教えていただけますか？",
        ask_about="番号",
        keep=["17:00", "18:00", "出口"],
    )
    rendered = plan.render()
    assert "1. 17:00〜18:00（担当: 出口）" in rendered
    assert "2. 18:00〜19:00（担当: 出口）" in rendered
    assert plan.rejects(rendered) is None
    assert "候補の番号が消えている" in (
        plan.rejects("17:00〜18:00（担当: 出口）と 18:00〜19:00（担当: 出口）が空いています。どちらがよいですか？") or ""
    )


def test_a_completed_action_may_be_reported_when_the_skeleton_says_so():
    """骨格が完了を伝えている場面では、完了を書いてよい。"""
    plan = ReplyPlan(
        facts=["2026/09/06 15:00のご予約をキャンセルしました。"],
        keep=["2026/09/06", "15:00"],
    )
    assert plan.rejects("2026/09/06 15:00のご予約をキャンセルしました。ご連絡ありがとうございました。") is None
