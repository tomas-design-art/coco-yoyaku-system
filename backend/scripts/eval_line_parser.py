"""LINE予約パーサーの精度評価ランナー（回帰テスト兼ベンチマーク）。

使い方（backend/ で実行）:
    python -m scripts.eval_line_parser

    # LLMも使って評価（GEMINI_API_KEY が .env にあれば自動でON）
    # 純ルールベースのみで評価したいとき:
    python -m scripts.eval_line_parser --rules-only

    # 失敗した項目だけ詳細表示:
    python -m scripts.eval_line_parser --failures-only

目的:
- backend/tests/data/line_parse_corpus.jsonl の各メッセージを parse_line_message に流し、
  期待値（intent検出 / date / time）と突き合わせて正答率を出す。
- 改修の前後で「72% → 88%」のように数値で効果を測るための基盤。
- constraints / intent種別（new/change/cancel）は現行パーサが未対応なので
  「未サポート（改修ターゲット）」として集計に出す。改修で produce するようになったら
  このランナーの compare を拡張して採点対象に含めること。

重要:
- 「今日」を 2026-08-13(木) に固定して評価する（相対日付の期待値がこの基準日で作られているため）。
  now_jst をこの日付にモンキーパッチする。
- 本番の実ログ（shadow_logsテーブル）から実メッセージを抜き出して
  このJSONLに追記していくほど、評価の実効性が上がる（種は同梱、実データで育てる）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# backend/ をパスに追加（-m 実行なら不要だが直接実行にも対応）
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.utils.datetime_jst import JST  # noqa: E402

CORPUS_PATH = BACKEND_DIR / "tests" / "data" / "line_parse_corpus.jsonl"
FIXED_NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=JST)  # 木曜。コーパス期待値の基準日


def _load_corpus() -> list[dict]:
    rows: list[dict] = []
    with CORPUS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _patch_now():
    """line_parser 内の now_jst を固定日時に差し替える。"""
    import app.agents.line_parser as lp

    lp.now_jst = lambda: FIXED_NOW  # type: ignore[assignment]


async def _run(rules_only: bool, failures_only: bool) -> int:
    _patch_now()

    from app.agents.line_parser import parse_line_message
    from app.config import settings

    if rules_only:
        settings.gemini_api_key = ""

    llm_on = bool(getattr(settings, "gemini_api_key", "")) and not rules_only

    corpus = _load_corpus()
    n = len(corpus)

    intent_ok = intent_kind_ok = date_ok = time_ok = constraint_ok = 0
    date_total = time_total = 0
    failures: list[dict] = []

    for case in corpus:
        parsed = await parse_line_message(case["message"])

        got_intent = bool(parsed.get("has_reservation_intent"))
        exp_intent = bool(case.get("expect_reservation_intent"))
        i_ok = got_intent == exp_intent
        intent_ok += int(i_ok)
        expected_kind = case.get("expect_intent")
        kind_ok = parsed.get("intent") == expected_kind if expected_kind else None
        intent_kind_ok += int(bool(kind_ok))

        expected_constraints = case.get("constraints", [])
        got_constraints = set(parsed.get("constraints") or [])
        constraints_ok = set(expected_constraints).issubset(got_constraints)
        constraint_ok += int(constraints_ok)

        # date/time は「期待値がある行」だけ分母に数える
        d_ok = t_ok = None
        if case.get("expect_date") is not None:
            date_total += 1
            d_ok = parsed.get("date") == case["expect_date"]
            date_ok += int(bool(d_ok))
        if case.get("expect_time") is not None:
            time_total += 1
            t_ok = parsed.get("time") == case["expect_time"]
            time_ok += int(bool(t_ok))

        if not (i_ok and kind_ok and constraints_ok and (d_ok in (None, True)) and (t_ok in (None, True))):
            failures.append(
                {
                    "id": case["id"],
                    "msg": case["message"],
                    "exp": {"intent": exp_intent, "date": case.get("expect_date"), "time": case.get("expect_time")},
                    "got": {"intent": got_intent, "kind": parsed.get("intent"), "date": parsed.get("date"), "time": parsed.get("time")},
                    "constraints": case.get("constraints", []),
                    "note": case.get("note", ""),
                }
            )

    def pct(a: int, b: int) -> str:
        return f"{(100 * a / b):.1f}%" if b else "—"

    print("=" * 72)
    print(f"LINE parser eval  (LLM={'ON' if llm_on else 'OFF/rules-only'}, cases={n}, today={FIXED_NOW.date()})")
    print("=" * 72)
    print(f"意図検出 (has_reservation_intent) : {pct(intent_ok, n)}   ({intent_ok}/{n})")
    print(f"意図種別一致 (intent)              : {pct(intent_kind_ok, n)}   ({intent_kind_ok}/{n})")
    print(f"日付一致 (date)                   : {pct(date_ok, date_total)}   ({date_ok}/{date_total})")
    print(f"時刻一致 (time)                   : {pct(time_ok, time_total)}   ({time_ok}/{time_total})")
    print(f"制約再現 (constraints)             : {pct(constraint_ok, n)}   ({constraint_ok}/{n})")
    print(f"完全失敗ケース数                  : {len(failures)}/{n}")
    print("-" * 72)
    print("=" * 72)

    if failures:
        print("\n[失敗ケース詳細]")
        for fail in failures:
            print(f"\n  #{fail['id']}  {fail['msg']!r}")
            print(f"    期待: {fail['exp']}")
            print(f"    実際: {fail['got']}")
            if fail["constraints"]:
                print(f"    制約(未対応含む): {fail['constraints']}")
            print(f"    狙い: {fail['note']}")
    elif not failures_only:
        print("\n全ケース pass 🎉")

    # 失敗があれば非ゼロ終了（CIで回帰検出に使える）
    return 1 if failures else 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules-only", action="store_true", help="LLMを使わずルールベースのみで評価")
    ap.add_argument("--failures-only", action="store_true", help="失敗ケースのみ表示")
    args = ap.parse_args()
    exit_code = asyncio.run(_run(args.rules_only, args.failures_only))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
