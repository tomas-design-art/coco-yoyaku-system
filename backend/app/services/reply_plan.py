"""返信の骨格をコードが作り、LLMには言い回しだけを任せる。

これまでは逆だった。LLMが返信の全文を書き、コードが後から検査して、
おかしければ書き直させていた。その形では、状態と文面が食い違う余地が残り続ける。
実機で起きたことがそれを示している（2026-09-04〜09-06）。

- コードは確認を待っていないのに、LLMが「はい・いいえで」と聞いた
- コードは予約を作っていないのに、LLMが「ご予約を承りました」と書いた
- コードは日時を受け取っているのに、LLMが「日時を教えてください」と聞き直した

穴を1つ塞ぐたび、LLMは別の言い方で同じことをする。検査を足し続ける限り終わらない。

そこで向きを変える。

    コードが骨格（伝える事実・選ばせる候補・尋ねること）を決める
        ↓
    LLM は言い回しだけを整える（事実と質問の増減はできない）
        ↓
    整えた結果が骨格を壊していたら、骨格をそのまま送る

骨格は単体で送れる完成した文面なので、LLMが使えなくても会話は止まらない。
「テンプレートに戻す」のとは違う。決めるのは骨格だけで、語り口はLLMが作る。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 「はい/いいえ」で答えさせる形。骨格が求めていなければ現れてはいけない。
_YES_NO_REQUEST = re.compile(r"はい[\s・/／、や]{0,3}いいえ|いいえ[\s・/／、や]{0,3}はい")
# 疑問符が無くても質問になる言い方があるので、そこまで数える。
_QUESTION_HINT = re.compile(r"[?？]|ましょうか|いかがでしょうか|いただけますか")
# 「済んだ」と伝える言い方。骨格が言っていなければ、その処理は実行されていない。
_OUTCOME_CLAIM = re.compile(
    r"(?:予約|お席)(?:を|が|も)?\s*(?:承り|確定し|お取りし|お取りいたし|完了し|承っ)(?:ました|ております)"
    r"|キャンセル(?:しました|いたしました|を承りました)"
    r"|(?:取消|取り消)(?:しました|いたしました)"
    r"|変更(?:しました|いたしました|を承りました)"
)


@dataclass
class ReplyPlan:
    """1通の返信に入れてよいものの全部。ここに無いものは書けない。"""

    # 患者へ伝える確定事実。DBから取った値だけを入れる。
    facts: list[str] = field(default_factory=list)
    # 番号で選ばせる候補。
    options: list[str] = field(default_factory=list)
    # 尋ねること。1通に1つだけ。
    ask: str | None = None
    # その質問が何についてのものか。質問文が別の話へ差し替えられていないかを見る。
    ask_about: str | None = None
    # 「はい / いいえ」で答えてもらうか。
    yes_no: bool = False
    # 一字も変えさせない語（日付・時刻・担当者名・メニュー名など）。
    keep: list[str] = field(default_factory=list)
    # 前置きの一言（初回の持ち物案内など）。
    note: str | None = None

    # ── 骨格 ────────────────────────────────────────────
    def render(self) -> str:
        """コードだけで作る、そのまま送れる文面。"""
        lines: list[str] = []
        if self.note:
            lines.append(self.note)
        lines.extend(self.facts)
        for index, option in enumerate(self.options, 1):
            lines.append(f"{index}. {option}")
        if self.ask:
            lines.append(self.ask)
        if self.yes_no:
            lines.append("はい / いいえ")
        return "\n".join(line for line in lines if line)

    # ── 整えた結果を受け入れてよいか ───────────────────────
    def rejects(self, polished: str) -> str | None:
        """骨格を壊していれば、その理由を返す。問題なければ None。

        検査する項目は骨格から決まる。場面ごとの規則を足していく必要がない。
        """
        if not polished or not polished.strip():
            return "空の返信"

        for term in self.keep:
            if term and term not in polished:
                return f"確定事実が消えている: {term}"

        for index in range(1, len(self.options) + 1):
            if f"{index}." not in polished and f"{index}．" not in polished:
                return f"候補の番号が消えている: {index}"

        # 骨格が伝えていない「済んだ」を足していないか。
        # 実際には何も実行していないのに「ご予約を承りました」と書いた（2026-09-06 実機）。
        if _OUTCOME_CLAIM.search(polished) and not _OUTCOME_CLAIM.search(self.render()):
            return "骨格に無い完了を伝えている"

        asks_yes_no = bool(_YES_NO_REQUEST.search(polished))
        if asks_yes_no and not self.yes_no:
            return "聞いていない「はい/いいえ」を求めている"
        if self.yes_no and not asks_yes_no:
            return "「はい/いいえ」の案内が消えている"

        sentences = [part.strip() for part in re.split(r"[。\n]", polished) if part.strip()]
        questions = [part for part in sentences if _QUESTION_HINT.search(part)]
        allowed = 1 if (self.ask or self.yes_no) else 0
        if len(questions) > allowed:
            return f"質問が増えている（{len(questions)}件／許可{allowed}件）"

        # 質問そのものが別の話へ差し替えられていないか。
        # 「キャンセルしてよろしいですか」が「別の日程をお取りしましょうか」に
        # 変わると、返ってきた「はい」の意味が反転する（2026-09-04 実機）。
        if self.ask_about and questions and self.ask_about not in questions[0]:
            return f"質問が別の話に変わっている（{self.ask_about} を尋ねていない）"

        return None


POLISH_PROMPT = """あなたは接骨院の受付です。次の文面を、患者へ送る自然で温かい日本語に整えてください。

守ること（破ったら送信されません）:
- 書かれている事実（日付・時刻・担当者・メニュー・施術時間）は一字も変えない。省略もしない
- 質問を増やさない。減らさない
- 書かれていない提案（別の日程・別の担当・料金・再予約の案内）を足さない
- 番号付きの候補は、番号と内容をそのまま残す
- 「はい / いいえ」の案内は、元の文面にあるときだけ残す。無ければ書かない

整えてよいのは、語順・接続・敬語・語尾・短いねぎらいの一言だけです。
JSONや説明は書かず、患者へ送る文面だけを返してください。

--- 文面 ---
{skeleton}
"""
