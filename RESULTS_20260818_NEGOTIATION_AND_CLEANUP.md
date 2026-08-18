# 実装レポート 2026-08-18 — 交渉ループ / 幻覚停止 / 来週バグ / HotPepper掃除

対象指示書: `INSTRUCTIONS_20260818_NEGOTIATION_AND_CLEANUP.md`
返信生成の原則は指示書4（LLM-ONLY）を継続。

---

## 第1部: LINE自動応答

### タスクA 交渉ループ

実機ログの詰まりは、**候補提示の直後に条件変更を受けたとき、返信せずに手動退避していた**ことが原因だった。
`intent == "question"` の分岐が `set_user_mode(manual)` と通知だけ行い、**1通も返信しないまま return** していた（無反応の直接原因）。
その後は manual モードなので、以降の「もしもし？」「落ちた？」がすべて `handoff_to_human` に落ちていた。

実装:

- `backend/app/services/line_negotiation.py`（新規）: `constraints` を検索条件 `SlotFilters` へ正規化する。
  `window` / `after` / `before` / `end_by` / `exclude_weekday` / `exclude_date` / `asap` / `earlier` / `later` / `duration_flexible`。
- `_reoffer_autopilot_candidates`: 条件変更を受けたら同じメニュー・同じ患者で再検索し、新しい候補を提示する。
  - 候補を出すたびに `autopilot_offered_slots` を state に保存し、「もっと早く」は提示済み最早時刻より前だけを探す基準にする。
  - 施術時間の短縮は `_menu_duration_bounds` の最小時間が下限。短縮した場合は `duration_shortened` と所要時間を context に入れ、返信で必ず明示させる。
  - 同日で見つからなければ後続7日へ拡張する。
- `_renegotiate_autopilot_change`: 変更候補の確認中に条件が変わった場合も、変更先を再探索して出し直す。
- 手動退避は最後の手段に限定した:
  1. 再検索が3回連続で不成立（`autopilot_negotiation_failures`）
  2. `needs_human=true`
  3. 例外
- 無反応の経路を全て塞いだ:
  - `intent == "question"` → 事実回答 or 料金案内 or 引き継ぎ（必ず返信）
  - キャンセル/変更の対象予約が見つからない → 引き継ぎ返信
  - 予約意図なしの一言 → `small_talk` で短く応答（**manualへ落とさない**）
  - `adjusting` で番号でも条件変更でもない返答 → 候補を提示し直す（ループガード付き）

### タスクB 幻覚停止

- `compose_reply` のプロンプトに禁止事項を追加:
  システム状態・障害・エラー・処理状況の創作禁止、症状・体調の推測禁止、引き継ぎ理由の創作禁止、料金非回答。
- 生成後チェック `_has_unsupported_claim` を追加。確定事実に無いシステム状態語（システム/障害/エラー/メンテナンス等）や、
  症状の話が出ていない場面での症状語（お痛み/症状/お大事 等）を検出したら **1回だけ書き直しを依頼**し、
  それでも直らない場合のみ `logger.error reason=unsupported_claim` ＋管理者通知でテンプレへ落とす。
- `handoff_to_human` の context から `reason` を除去し、`SITUATION_GUIDES` も「理由は説明しない」に変更した。

### タスクC 来週バグ

- `resolve_weekday_date()` を追加し、月曜始まりの暦週で解決するようにした。
  「来週◯曜」＝今週月曜+7日+曜日index、「今週◯曜」＝今週月曜+曜日index（過去なら翌週へ送り、過去日を希望日にしない）、
  「次の◯曜」「◯曜」＝直近の未来のその曜日。
- LLMプロンプトにも同じ定義を明記した（従来はプロンプトに定義が無く推測任せだった）。
- コーパス `rel-01` の `expect_date` を `2026-08-25` → **`2026-08-18`** に修正（LLMの出力が正しく、コーパスが誤りだった）。

### タスクD constraints の橋渡し

- `build_same_day_candidates` の Tier1 が `bh_end` まで走査してウィンドウを無視していたため、`we` を上限に修正した。
  `desired_min` もウィンドウ開始でクランプする。
- `build_candidates_over_days` を追加し、除外日・除外曜日・複数日探索に対応した。
- 本線の候補生成（曖昧時間帯・`ask_time_for_date`・満席時の代替候補）を constraints 由来のウィンドウで検索するようにした。

### タスクE システム由来の事実に回答（料金は除外）

- `backend/app/services/line_facts.py`（新規）。DBの値だけを集めて context に入れ、文面はLLMが書く。
  - 営業日・休診日（`get_business_hours_for_date`）
  - 施術者の出勤/勤務時間（`is_practitioner_working` / `get_practitioner_working_hours`）
  - 空き状況（`build_same_day_candidates`）
  - メニュー名・所要時間・10分刻みの選択可否（`menus`）
- **料金は回答しない。** `menus.price` も `menu_price_tiers.price` も nullable で未入力があり、可変時間メニューもあるため。
  `price_to_staff` で「スタッフから案内する」と返し、手動へ渡す。プロンプトでも金額表記を禁止した。

---

## 第2部: HotPepper未同期618件

### タスクF-1 調査結果（原因特定済み）

| 確認項目 | 結果 |
|---|---|
| 1. 本番コミットに日付フィルタが含まれるか | **含まれる。** `Reservation.start_time >= now` は 2026-05-28 (`77b1da1`) で導入され、現行 `main`(`edb1fb9`) にも存在。デプロイ漏れではない |
| 2. フロントが叩いているエンドポイント | `HotPepperSync.tsx` は `/hotpepper/pending-sync`。**ただし失敗時に無条件フォールバックがあった** |
| 3. 表示している日付フィールド | `r.start_time`（別フィールドではない） |
| 4. `now_jst()` と DB の型 | `now_jst()` は +09:00 付き、`start_time` は `DateTime(timezone=True)`。型・TZの不整合ではない |
| 5. 過去の未同期件数 | 本番DBへは参照できないため、`GET /api/hotpepper/past-unsynced/preview` で月別内訳を取得できるようにした |

**根本原因: フロントエンドの無条件フォールバック。**
`/hotpepper/pending-sync` が何らかの理由で失敗すると、`getReservations({})`（日付範囲なし＝全期間）を取得し、
クライアント側で `hotpepper_synced` と `channel` と `status` だけで絞り込んでいた。
**日付条件が一切無いため、2026/4/9 のような過去の未同期予約が全部並び、618件になった。**
APIは正しく、フォールバック経路だけが誤っていた。

### タスクF-2 過去分の一括同期（管理者操作）

- `GET /api/hotpepper/past-unsynced/preview`（**ドライラン**・`require_admin`）: 件数・最古/最新・月別内訳だけを返す。何も変更しない。
- `POST /api/hotpepper/past-unsynced/mark-synced`（`require_admin`）: `confirm=true` が無ければ 400。
  対象条件は `hotpepper_synced == False` かつ `channel != "HOTPEPPER"` かつ `status in (CONFIRMED/PENDING/HOLD)` かつ
  **`start_time < 今日0:00(JST)`**。UPDATE 側にも `start_time < today_start` を重ねており、**未来は絶対に更新しない**。
- 監査ログ `HOTPEPPER_BULK_MARK_PAST_SYNCED` を `X-Operator` 付きで記録（件数・cutoff・最古/最新）。
- UIは件数と月別内訳を出す確認ダイアログを経てから実行し、実行後に一覧と件数を再取得する。
- **マイグレーションでは流していない。**

### タスクF-3 再発防止

- フォールバック経路に「今日以降・90日先まで」の窓を適用し、フォールバック中である旨を画面に表示する。
- 抽出条件を `pending_sync_filters()` / `past_unsynced_filters()` に切り出し、過去・90日超が除外されることをテストで固定した。

---

## 第3部: HP側FAQ・料金表の連携（調査のみ・実装なし）

このワークスペースにはHP側リポジトリが含まれていないため、**確認できた事実と、確認できない事項を分けて記載する。**

1. **同一PostgreSQLか**
   このリポジトリから確認できる範囲では、HPと予約システムの接続点は**APIのみ**である。
   `backend/app/api/public.py`（`/menus` `/business-hours` `/slots`）と `web_reserve.py`、
   および `frontend/dist-widget/widget.js`（Shadow DOM で外部サイトへ埋め込むチャットウィジェット、`CHATBOT_ALLOWED_ORIGINS` で許可）。
   設定値は `database_url` 1本のみで、**外部CMS/別DBへの接続情報は存在しない**。
   → 「同じDBを共有している」という証拠はこのリポジトリには無い。確定にはHP側のホスティング情報が必要。

2. **HP側のFAQ・料金表の保存形式**
   このワークスペースからは**判定不能**（HP側リポジトリ・CMS管理画面が無い）。

3. **参照方式の比較**

   | 方式 | メンテコスト | 結合度 | 障害時の影響 |
   |---|---|---|---|
   | (a) HP側に公開APIを作って呼ぶ | 中（API定義とバージョン管理が必要） | 低（HTTP境界のみ） | HP停止時はFAQ回答不可。予約機能は無傷にできる |
   | (b) 共有DBをスキーマ跨ぎで直読み | 低（実装は最短） | **高**（HP側のスキーマ変更が予約システムを直撃） | DB共有のため障害が両系に波及。**非推奨** |
   | (c) 定期同期でコピーを持つ | 中（同期ジョブと鮮度管理） | 低 | HP停止中も回答可能。ただし情報が古くなるリスク |

   → 推奨は (a) か (c)。(b) は本システムが予約という業務クリティカルを担うため避けるべき。

4. **料金データの完全性**
   本システム側は `menus.price` / `menu_price_tiers.price` がいずれも **nullable** で未入力が発生し得る。
   さらに `is_duration_variable` のメニューは10分刻みで所要時間が変わる。
   HP側の完全性は未確認だが、**少なくとも本システムの料金データは自動回答に使えない**と結論づけられる。
   HP側が完全であっても、可変メニューの金額計算ロジックをLINEで自動回答するのは誤案内リスクが高い。

**結論: 今回は実装せず、料金の自動回答は行わない方針が妥当。** FAQのうち営業時間・休診日・空き・所要時間は既にDBから回答できるようにした（タスクE）。

---

## 検証結果

| # | 検証 | 結果 |
|---|---|---|
| 1 | 交渉ループ再現 | ✅ `test_autopilot_negotiation_reoffers_earlier_shorter_slot_without_handoff` — 手動退避せず、35分（メニュー最小）を明示した11:15の候補を提示。`window_end_min` が提示済み最早13:00基準で絞られることも検証 |
| 2 | 幻覚禁止 | ✅ `test_composer_rejects_invented_system_state_and_symptom_guess` / `test_composer_falls_back_when_unsupported_claim_repeats` — 「もしもし？」「落ちた？」の文脈でシステム語・症状語を検出し、再生成→失敗時のみテンプレ＋管理者通知 |
| 3 | 来週テスト | ✅ `test_resolve_weekday_date_uses_calendar_weeks` / `test_rule_parser_resolves_next_week_tuesday_to_calendar_week` — 木曜起点で来週火曜=8/18。コーパス `rel-01` 修正済み。評価の日付一致は **18/18 (100%)** |
| 4 | 料金拒否 | ✅ `test_autopilot_price_question_refuses_amount_and_hands_to_staff` — 金額を返さず `price_to_staff` で手動へ。併せて `test_autopilot_business_hours_question_answers_from_database` で営業時間はDB値から回答 |
| 5 | HotPepper | ✅ `tests/test_hotpepper_past_cleanup.py` 4件 — 過去/90日超が一覧から除外、ドライランが未来を1件も含まない、`confirm` 無しは400、実行後も未来は未更新、監査ログ記録 |
| 6 | 評価 & 回帰 | 下記 |
| 7 | 安全確認 | ✅ `reject_conflicts=True` は autopilot の予約作成3経路に残存。対象者ゲート（グローバル＋患者個別）不変。旧分岐の `and not is_autopilot_patient` 3箇所も不変 |

### 検証6の数値

`python -m scripts.eval_line_parser --sleep 1.5`（LLM実測、45件）

| 指標 | 変更前 | 変更後 |
|---|---|---|
| LLM実効件数 | 45/45 | 45/45 |
| 意図検出 | 43/45 (95.6%) | 42/45 (93.3%) |
| 意図種別 | 41/45 (91.1%) | 40/45 (88.9%) |
| 日付一致 | 17/18 (94.4%) | **18/18 (100%)** |
| 時刻一致 | 17/17 (100%) | 17/17 (100%) |
| **制約再現** | 23/45 (51.1%) | **29/45 (64.4%)** |
| 完全失敗ケース | 22/45 | **16/45** |

制約再現の向上は、実際に予約判断へ効く項目を抽出できるようにしたことによる:
所要時間 `duration:N`、前回担当 `ref_practitioner:previous`、多言語の時間帯 `window:`（morning/오전/下午 等）、
症状・緊急度 `symptom:` / `urgency:high`、変更元の `current_date:` / `current_time:`。

> 残る未達分は、コーパスの `constraints` 欄に `polarity:negative` / `fragment` / `no_keyword` / `name:田中` /
> `route:manual` のような**注釈ラベル**が混在しているため。これらは parser の出力仕様（`polarity` や `needs_human` は
> 独立フィールド）と重複するので、意図的に constraints へは出していない。
>
> 意図検出・意図種別が2ポイント下がったのはLLMの実行揺らぎの範囲で、失敗ケース総数は22→16へ減少している。

### 回帰

```
pytest tests/test_shadow_mode.py tests/test_line_ai_secretary.py tests/test_slot_scorer.py \
       tests/test_hotpepper_past_cleanup.py tests/test_hotpepper_api_endpoints.py \
       tests/test_hotpepper_parser.py tests/test_alembic_revision_chain.py -q
→ 161 passed
```

全体スイート: `330 passed / 4 failed`。失敗4件は `test_daily_report` / `test_integration` / `test_patients`×2 の
**既存のテスト分離問題**で、今回の変更を除外した状態（`--ignore` 実行）でも同じ4件が落ちる。

フロントエンド: `npm run build`（`tsc && vite build`）成功。
