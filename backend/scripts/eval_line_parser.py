"""LINE予約パーサーの精度評価ランナー（回帰テスト兼ベンチマーク）。

使い方（backend/ で実行）:
    python -m scripts.eval_line_parser              # LLM込み（GEMINI_API_KEYがあれば自動ON）
    python -m scripts.eval_line_parser --rules-only # 純ルールベースのみ
    python -m scripts.eval_line_parser --failures-only
    python -m scripts.eval_line_parser --sleep 2.0  # 呼び出し間隔を長めに（429対策）

目的:
- backend/tests/data/line_parse_corpus.jsonl の各メッセージを parse_line_message に流し、
  期待値（intent検出 / intent種別 / date / time / constraints）と突き合わせて正答率を出す。
- 改修の前後で数値で効果を測るための基盤。

429（レート制限）対策:
- 各ケースの間に --sleep 秒の待ちを入れる（既定1.0秒）。
- LLM呼び出しが失敗したら指数バックオフで最大2回まで再試行する。
- 「LLM実効件数」を表示し、LLMが本当に効いたか／全部フォールバックしたかを可視化する。
  ここが 0/45 なら精度はルールベースのままなので、数値がLLMの実力を表さない。

重要:
- 「今日」を 2026-08-13(木) に固定して評価する（相対日付の期待値がこの基準日で作られているため）。
- 本番の実ログ（shadow_logsテーブル）から実メッセージを抜き出して追記するほど実効性が上がる。
"""
from __future__ import annotations

import argparse
import asyncio
import json
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


def _install_llm_probe(retries: int, backoff: float) -> dict:
    """_ai_parse をラップして (1)成功/失敗を数える (2)429等の失敗を指数バックオフで再試行する。

    戻り値の dict に llm_ok / llm_fail が積算される。
    """
    import app.agents.line_parser as lp

    stats = {"llm_ok": 0, "llm_fail": 0}
    original = lp._ai_parse

    async def _wrapped(message, *args, **kwargs):
        # 引数はそのまま透過させる（parser側の引数追加でプローブが壊れないように）
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                result = await original(message, *args, **kwargs)
                stats["llm_ok"] += 1
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(backoff * (2 ** attempt))
        stats["llm_fail"] += 1
        assert last_exc is not None
        raise last_exc

    lp._ai_parse = _wrapped  # type: ignore[assignment]
    return stats


async def _run(rules_only: bool, failures_only: bool, sleep: float, retries: int, backoff: float) -> int:
    _patch_now()

    from app.agents.line_parser import parse_line_message
    from app.config import settings

    if rules_only:
        settings.gemini_api_key = ""

    llm_on = bool(getattr(settings, "gemini_api_key", "")) and not rules_only
    llm_stats = _install_llm_probe(retries, backoff) if llm_on else {"llm_ok": 0, "llm_fail": 0}

    corpus = _load_corpus()
    n = len(corpus)

    intent_ok = intent_kind_ok = date_ok = time_ok = constraint_ok = 0
    date_total = time_total = 0
    failures: list[dict] = []

    for idx, case in enumerate(corpus):
        parsed = await parse_line_message(case["message"])
        if llm_on and sleep > 0 and idx < n - 1:
            await asyncio.sleep(sleep)  # レート制限回避のスロットリング

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
                    "exp": {"intent": exp_intent, "kind": expected_kind, "date": case.get("expect_date"), "time": case.get("expect_time")},
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
    if llm_on:
        total_llm = llm_stats["llm_ok"] + llm_stats["llm_fail"]
        print(f"LLM実効件数 (成功/試行)           : {llm_stats['llm_ok']}/{total_llm}   （失敗={llm_stats['llm_fail']}）")
        if llm_stats["llm_ok"] == 0:
            print("  ⚠ LLMが1件も成功していません。全ケースがルールへフォールバック＝数値はLLMの実力ではありません。")
        print("-" * 72)
    print(f"意図検出 (has_reservation_intent) : {pct(intent_ok, n)}   ({intent_ok}/{n})")
    print(f"意図種別一致 (intent)              : {pct(intent_kind_ok, n)}   ({intent_kind_ok}/{n})")
    print(f"日付一致 (date)                   : {pct(date_ok, date_total)}   ({date_ok}/{date_total})")
    print(f"時刻一致 (time)                   : {pct(time_ok, time_total)}   ({time_ok}/{time_total})")
    print(f"制約再現 (constraints)             : {pct(constraint_ok, n)}   ({constraint_ok}/{n})")
    print(f"完全失敗ケース数                  : {len(failures)}/{n}")
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
    ap.add_argument("--sleep", type=float, default=1.0, help="各ケース間の待ち秒（429対策。既定1.0）")
    ap.add_argument("--retries", type=int, default=2, help="LLM失敗時の再試行回数（既定2）")
    ap.add_argument("--backoff", type=float, default=2.0, help="再試行の基準待ち秒（指数バックオフ。既定2.0）")
    args = ap.parse_args()
    exit_code = asyncio.run(_run(args.rules_only, args.failures_only, args.sleep, args.retries, args.backoff))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
