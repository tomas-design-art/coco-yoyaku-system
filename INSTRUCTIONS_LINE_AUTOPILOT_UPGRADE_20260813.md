# 指示書: LINE自動応答（autopilot）を「有能な秘書」へ引き上げる改修

作成: 2026-08-13 / 対象実装者: VS Code Copilot / 対象リポ: `Yoyaku_AppV2`

---

## この改修のゴール（一言で）

現状のLINE autopilotは **「着物を着た入力フォーム」** になっている。
原因は2つ:

1. **LLMが患者向けの返事を一言も書いていない**（全部が固定テンプレ文）。
2. **LLMは正規表現が失敗したときだけ呼ばれる補欠**（[backend/app/agents/line_parser.py](backend/app/agents/line_parser.py) の `parse_line_message` が rule-first short-circuit）。

この2点を反転させ、**予約判断のロジック（どの枠を押さえるか）はコードのまま安全に保ちつつ、「言葉の理解」と「言葉の生成」だけをLLMに委ねる**。
結果として「ベテラン事務員が受付をさばいている」体感を作る。

---

## 🔒 絶対に守る原則（先に読む）

改修中、以下は**壊してはいけない／勝手に変えてはいけない**:

1. **予約確定の判断はコードが持つ。** 空き判定・競合検出・営業時間・勤務時間チェックは
   [backend/app/services/reservation_service.py](backend/app/services/reservation_service.py) の既存ロジックを使う。**LLMに「予約してよいか」を判断させない。**
2. **競合枠への自動確定は禁止。** autopilotの確定は既に `create_reservation(..., reject_conflicts=True)` を使っている（[line.py:1064](backend/app/api/line.py) 等）。**この `reject_conflicts=True` を外さない。** LINEチャネルはオンライン扱いで通常は競合を許容して赤帯表示するが、無人autopilotでは絶対に競合の上に重ねない。
3. **対象者ゲートは現行方式を維持。** `settings.line_autopilot_enabled`（グローバルスイッチ）＋ `patients.line_autopilot_enabled`（患者個別）＋合言葉 `#autopilot-setup` 自己登録。**allowlist方式には変えない。** 判定は `is_autopilot_patient` で一元化されている（[line.py:953](backend/app/api/line.py)）。ここを触らない。
4. **autopilot対象外の患者のフローは1バイトも変えない。** shadow_mode等の既存分岐（[line.py:962](backend/app/api/line.py)）はそのまま。
5. **LLM呼び出しは必ずフォールバックを持つ。** タイムアウト・APIエラー・JSON壊れ時は、**現行のテンプレ文／ルールベース結果に必ず落ちる**。LLMが落ちても予約機能が死なないこと。
6. **個人情報を外部に出さない範囲を維持。** LLMへ送るのはメッセージ本文と、必要なら患者の表示名・メニュー一覧まで。カルテ番号・電話番号・生年月日をプロンプトに載せない。
7. **既存テストを壊さない。** 改修後 `pytest` の既存グリーンを維持（既知の分離失敗4件=`test_daily_report.py` / `test_integration.py::test_phone_reservation_no_menu_pending` / `test_patients.py`2件 は対象外、これらは元から落ちる）。

---

## 改修タスク一覧（この順で実施）

| # | タスク | 効果 | 労力 | 主対象ファイル |
|---|---|---|---|---|
| A | autopilotにデバウンス導入 | 分割送信の催促連発を解消 | 小 | line.py, shadow_service.py(流用) |
| B | パーサをLLM主・ルール従へ反転＋プロンプト統一強化 | 解析精度が跳ねる | 中 | line_parser.py |
| C | 意図分類・肯定否定判定をLLMベースへ | 誤ルーティング解消 | 中 | line_parser.py, line.py |
| D | 返事の文面をLLM生成に（compose_reply） | 「人間っぽさ」が一気に出る | 中 | 新規 line_composer.py, line.py |
| E | 確認往復の削減 | 有能さ＝往復の少なさ | 小 | line.py |
| F | エラー／エッジ文言の人間化 | 開発者向け文言の撲滅 | 小 | line.py |

各タスクの後に **必ず** 評価ランナー（後述）を回して数値を記録すること。

---

## タスクA — autopilotにデバウンス（分割送信の統合）

### 問題
LINEユーザーは「予約したい」「明日の」「14時で」と**分けて**送る。現状 autopilot 経路（[line.py](backend/app/api/line.py) `_handle_text_message`）には**デバウンスが無く**、3通が別々に処理され「日時を教えてください」を2回催促してしまう。
一方 shadow 経路には `debounce_message` / `flush_debounce`（[backend/app/services/shadow_service.py](backend/app/services/shadow_service.py)）が既にある。

### やること
1. `shadow_service.py` のデバウンス機構（`_DEBOUNCE_BUFFER` / `_DEBOUNCE_SECONDS=10` / `debounce_message` / `flush_debounce` / `_is_duplicate_shadow_message`）を、**汎用モジュール** `backend/app/services/line_debounce.py` に切り出す（shadow側はそれをimportして使うよう置換。挙動は不変に保つ）。
2. `_handle_text_message` の autopilot 分岐の**入口**で、`is_autopilot_patient` のときにデバウンスを通す。実装方針:
   - Webhookは即 `200` を返す必要があるため、LINEの `reply_token` は約1分で失効する点に注意。**長い固定sleepは入れない。**
   - 推奨: 「短時間（例: 直近8〜10秒）の同一ユーザー未完了ドラフトに、新着メッセージを**追記マージ**してから解析する」方式。既存の `merge_user_draft`（[line_state.py](backend/app/services/line_state.py)）でドラフトは既に蓄積される設計なので、**『1メッセージごとに即・全項目を要求せず、足りない分だけ聞く』を徹底**すれば、多くはデバウンスなしでも救える。まずこの「追記マージの穴」を塞ぐことを優先し、真の時間デバウンスは shadow 同等機構の移植で対応する。
3. 重複Webhook（同一event二重配信）対策 `_is_duplicate_shadow_message` 相当も autopilot 経路に適用する。

### 完了条件
- `frag-01` → `frag-02` → `frag-03`（コーパス）を連続で送ったとき、催促は最小限（理想は0〜1回）で「明日14時」を1件の予約意図として組み立てられる。
- shadow経路の既存テスト（`test_shadow_mode.py`）が緑のまま。

---

## タスクB — パーサをLLM主・ルール従へ反転＋プロンプト統一強化（★最重要）

### 問題
- [line_parser.py:211](backend/app/agents/line_parser.py) で **rule-first short-circuit**（日付＋時刻が正規表現で取れたらLLMを呼ばない）。
- autopilotが使う `LINE_PARSE_PROMPT` は薄い（few-shot無し・intent分類無し・confidence無し・constraint無し）。
- 一方 shadow の `_SHADOW_PARSE_PROMPT`（[shadow_service.py](backend/app/services/shadow_service.py)）の方が優秀なのに、**autopilotはshadowをバイパスするので使えていない**。

### やること
1. **解析の主従を反転**: `parse_line_message` を「LLMを主、ルールを検算・フォールバック」に変える。
   - 方針: `settings.gemini_api_key` があれば **常にLLMを先に実行**。ルールベース結果は (a) LLM失敗時のフォールバック、(b) LLM結果の妥当性チェック（例: LLMが過去日を返したら破棄）に使う。
   - LLM呼び出しは `temperature=0`。ネットワーク/JSONエラーは try/except でルールベースへ。
2. **プロンプトを1本に統一・強化**（下記「新プロンプト」を採用）。以下を produce する:
   - `intent`: `new` | `change` | `cancel` | `question` | `other`
   - `has_reservation_intent`: bool
   - `name`（自名乗り時のみ）, `menu_hint`, `date`, `time`
   - `current_date` / `current_time`（変更時の既存予約参照）
   - `duration_minutes`
   - `constraints`: 配列（`end_by:HH:MM` / `after:HH:MM` / `exclude_weekday:wed` / `asap` / `window:HH:MM-HH:MM` / `symptom:...` / `ref_history` / `date_range:month_end` など）
   - `polarity`: `affirmative` | `negative` | `none`（確認への返事解釈用）
   - `confidence`: `high` | `medium` | `low`
   - `needs_human`: bool（相談・領収書・クレーム等、無人で完結すべきでない）
3. **メニュー一覧をDBから動的に注入**する。`_extract_menu` の5語ハードコードを廃し、`menus` テーブルの有効メニュー名をプロンプトに渡して **LLMに実メニューへマッピングさせる**（症状→メニューもここで解決）。「肩こり」「寝違え」等は該当メニュー（多くは保険診療）に寄せる。
4. **時間帯の点マッピングは残しつつ、`window` も併記**。「午前中」は `time:10:00` かつ `constraints:["window:00:00-12:00"]`。「夕方5時」のように**具体時刻があるときは時刻を尊重**し丸めない（コーパス `time-var-01`）。
5. `constraints` を autopilot の候補生成（`build_same_day_candidates` / `score_candidates`）に橋渡しする薄いアダプタを作る（`end_by`/`after`/`window`/`exclude_weekday`/`asap`）。まずは `window`・`after`・`end_by`・`asap` の4つを候補フィルタに反映できれば十分。

### 新プロンプト（`line_parser.py` にこの内容で置換）

````text
あなたは接骨院の熟練予約秘書AIです。患者からのLINEメッセージを解析し、必ずJSONのみで返します（説明文禁止）。
今日は {today}（{weekday}曜日）。メッセージは日本語/英語/中国語/韓国語など任意の言語で届きます。言語を問わず意味を取り、日付時刻は必ず正規化してください。

当院の有効メニュー一覧（この中の名称にマッピングすること。無理に決めず不明ならnull）:
{menu_list}

出力JSON（全キー必須）:
{{
  "intent": "new | change | cancel | question | other",
  "has_reservation_intent": true/false,
  "name": "患者が自ら名乗った氏名 or null（本文に無ければ創作しない）",
  "menu_hint": "上記一覧の名称 or 'usual'（いつも/前回同様） or null",
  "date": "希望日 YYYY-MM-DD or null",
  "time": "希望時刻 HH:MM or null",
  "current_date": "変更対象の既存予約日 YYYY-MM-DD or null",
  "current_time": "変更対象の既存予約時刻 HH:MM or null",
  "duration_minutes": 整数 or null,
  "constraints": ["制約の配列。該当なければ空配列"],
  "polarity": "affirmative | negative | none",
  "confidence": "high | medium | low",
  "needs_human": true/false
}}

■ intent 判定:
- new: 新規予約希望（空き確認・「取りたい」含む）
- change: 既存予約の日時変更（「ずらす」「別の日で」「変更」）
- cancel: 取消・欠席（「キャンセル」だけでなく「行けなくなった」「やめておく」「予定が入った」等キーワード無しの取消も含む）
- question: 営業時間・料金・領収書など問い合わせ（予約ではない）
- other: お礼・雑談・確認への相槌など

■ polarity（直前の提案への返事を解釈）:
- 「大丈夫」を含んでも「大丈夫じゃない」は negative。「難しい」「無理」「やめておく」は negative。
- 「それで」「おけ」「はい」「お願いします」は affirmative。判断できなければ none。

■ 日時ルール:
- 相対日付「今日/明日/明後日/来週◯曜/次の◯曜」は today 基準で未来へ解決。「来週◯曜」は直近のその曜日+7日。
- 時間帯→時刻: 朝/朝一=09:00, 午前(中)=10:00, 昼/お昼=12:00, 午後イチ=14:00, 午後=14:00, 夕方=17:00, 夜/晩=19:00。
  ただし「夕方5時」のように具体時刻があればそれを優先し丸めない。
- 曖昧時間帯は time に代表値、constraints に window を併記（例: 午前→ time:10:00, constraints:["window:00:00-12:00"]）。
- 挨拶の「夜分遅くに失礼します」等の時間語は希望時刻として使わない。

■ constraints の書式（該当するものだけ）:
- "end_by:HH:MM"（〜までに終わりたい）/ "after:HH:MM"（〜以降）/ "before:HH:MM"（〜まで）
- "window:HH:MM-HH:MM"（時間帯）/ "asap"（なるべく早く）
- "exclude_weekday:mon|tue|wed|thu|fri|sat|sun" / "exclude_date:YYYY-MM-DD"
- "date_range:month_end" 等の期間 / "symptom:内容" / "duration:分" / "ref_history"（前回同様）/ "ref_practitioner:previous"

■ needs_human=true にすべき例: クレーム、痛みが強く緊急性が高い相談、領収書・保険・料金の個別問い合わせ、
  本人確認が必要な機微情報のやりとり。判断に迷ったら needs_human=true 側に倒す。

■ name は「〜です」「〜と申します」等の自名乗りのみ。話題に出た第三者名は入れない。本人確認済みなら name は null で良い。

メッセージ:
{message}

JSON:
````

- `{menu_list}` は `menus` テーブルの有効メニュー（name と duration・可変フラグ程度）を箇条書きで注入。
- 既存の後処理（`_normalize_name` / 時刻ゼロ埋め）は流用可。

### 完了条件
- 評価ランナー（`--rules-only` でない通常＝LLM ON）で **date一致・time一致・intent検出がベースラインから明確に向上**（数値を記録）。
- コーパスの `constraint-*` `symptom-*` `multi-*`（英中韓）`noise-*` が拾えるようになる。
- LLMを切った（`--rules-only`）状態でも既存の基本ケース（`base-*`）は通る＝フォールバック健在。

---

## タスクC — 意図分類・肯定否定判定をLLMベースへ

### 問題
[line.py:659-687](backend/app/api/line.py) の `_is_affirmative` / `_is_negative` / `_has_cancellation_intent` / `_has_change_intent` / `_requires_manual_autopilot_handling` は**全部substring一致**で脆い。
- 「大丈夫じゃない」→ 誤って肯定
- 「予定が入っちゃって」→ 取消と認識されない
- 「ちょっと難しい」→ 否定と認識されない

### やること
1. タスクBのパーサが返す `intent` / `polarity` を**一次情報として使う**ようにルーティングを付け替える:
   - キャンセル/変更/相談の分岐は、まず `intent` を見る。キーワード関数は**後方互換のフォールバック**としてのみ残す。
   - 確認モード（`autopilot_booking_confirm` / `autopilot_change_confirm` / `autopilot_cancel_confirm` / `autopilot_confirm_usual`）での「はい/いいえ」判定は `polarity` を優先し、`_is_affirmative/_is_negative` はフォールバックに降格。
2. `needs_human=true` を受けたら、確定・提案に進まず **`manual` モードへ退避 + 管理者へ通知**（既存の manual 退避・[line.py:1587](backend/app/api/line.py) 付近の仕組みを流用）。
3. `_is_affirmative` の誤爆源（「それで」等の部分一致、「大丈夫」の否定文脈）は、LLM polarity を主にすることで実質解消。関数自体は残すが、否定を先に見る現行順序は維持。

### 完了条件
- コーパス `affneg-01..04` `change-03` `cancel-02` `casual-01` `clarify-02` が正しく分類される（intent/polarity採点は評価ランナーを拡張して計測、下記参照）。

---

## タスクD — 返事の文面をLLM生成に（compose_reply）

### 問題
全 `reply_to_line(...)` が固定テンプレ。だから何を言われても同じロボット文。これが「テンプレ感」の正体。

### やること（安全第一の設計）
1. 新規 `backend/app/services/line_composer.py` に `compose_reply(situation, context) -> str` を作る。
   - **入力**: `situation`（列挙: `ask_datetime` / `ask_menu` / `confirm_slot` / `confirmed` / `offer_alternatives` / `first_visit_note` / `cancel_done` / `change_done` / `handoff_to_human` / `parse_failed` など）と、`context` dict（患者名・確定した日時・担当名・メニュー・候補リスト・初回か・症状ワード等の**事実**）。
   - **出力**: 1〜3文の自然な日本語。敬語・簡潔・親しみ。
2. **LLMには「事実」だけ渡し、事実の創作を禁止**する。プロンプトで:
   - 「与えられた日時・担当・メニューの値のみを使う。空き状況や新事実を発明しない。番号や日時を改変しない。」
   - 「1メッセージ1論点。長文にしない。絵文字は控えめ（最大1つ）。」
3. **必ずテンプレ・フォールバック**を持つ。LLM失敗時は現行の固定文（＝今のテンプレ）をそのまま返す。`compose_reply` は「失敗しても必ず文字列を返す」契約にする。
4. 置換範囲: まず**体感が大きい所から**。`ask_datetime`（日時を聞く）/ `confirm_slot`（枠提示）/ `confirmed`（確定）/ `offer_alternatives`（候補提示）の4つを優先的にLLM化。エラー系はタスクFで。
5. **症状への共感**をcontextで渡せるようにする（例: `symptom="腰"` なら「お腰つらいですね、お大事に」を一言添える）。ただし医療アドバイスはしない（「様子見て」「湿布を」等の指示は禁止＝プロンプトで明示）。

### compose_reply プロンプト骨子
````text
あなたは接骨院の受付ベテラン事務員です。以下の「確定事実」だけを使い、患者への短い返信を作ってください。
- 事実にない日時・空き・診療内容を作らない。数値・番号・固有名は与えられた通りに使う。
- 敬語で簡潔に。1〜3文。絵文字は最大1つ。1メッセージ1論点。
- 医療的な指示・診断はしない（「湿布を」「安静に」等は書かない）。痛みには一言いたわる程度に留める。
状況: {situation}
確定事実(JSON): {context_json}
返信文:
````

### 完了条件
- 同じ「日時を聞く」場面でも、患者の言い回し（症状・急ぎ度）に応じて文面が自然に変わる。
- LLMを切ると現行テンプレ文がそのまま出る（回帰なし）。

---

## タスクE — 確認往復の削減

### 問題
既知患者が「明日14時に骨盤で」と**言い切っても**、なお「はい/いいえ」を挟む場面がある（`autopilot_confirm_usual` / `autopilot_booking_confirm`）。有能さは往復の少なさで伝わる。

### やること
1. **必要情報が1メッセージで揃い、かつ `confidence:high` かつ空き枠が確保できる**場合は、確認をスキップして**即確定**（`create_reservation(reject_conflicts=True)` → `confirmed` 返信）。
   - 例: 既知患者「いつもので明日14時」→ usual確定 + 空きあり → 確認省略で確定。
2. **番号選択は既に即確定**（[line.py:1101](backend/app/api/line.py)「番号選択＝明示的確定意思」）。この設計を他にも展開。
3. 逆に **`confidence:low` や新規患者・初回** は従来通り1回確認を残す（安全側）。
4. 「いつものでよろしいですか？」も、同じ文に日時が含まれていれば（既存の [line.py:1240](backend/app/api/line.py) 付近の部分対応を拡張して）**確認を省いて日時確定へ**。

### 完了条件
- コーパス `multi-slot-01` `multi-slot-02` 相当が、（空きがあれば）確認1回以内で確定に到達。
- 新規・低確信は確認が残る。

---

## タスクF — エラー／エッジ文言の人間化

### 問題
[line.py:1675](backend/app/api/line.py)「日時の解釈に失敗しました。例: 4/10 10:00 の形式で送信してください。」等、**開発者向けの文言が客に出ている**。

### やること
1. こうした文言を `compose_reply(situation="parse_failed", ...)` 等に置換し、「うまく聞き取れず申し訳ありません。ご希望の日にちと時間帯をもう一度教えていただけますか？（例: 明日の午後3時ごろ）」のような**受付らしい文**にする。
2. 営業時間外・休診日希望（`validate_business_hours` が400を返す前）に、**AI側で先回りして**「その時間は診療時間外でして…○○ならご案内できます」と返す。`get_business_hours_for_date` を確定前に参照し、範囲外なら候補提示に切り替える。
3. 「担当者が確認中です」等の manual 退避文も、状況に応じた自然文へ。

### 完了条件
- 客に開発者用エラー文が一切出ない。営業時間外希望で例外落ちせず、案内文になる。

---

## 評価基盤（この改修の心臓部）

**「作って院長と使って“微妙”と目視」から卒業する。** 数値で測る。

### 同梱物
- コーパス: [backend/tests/data/line_parse_corpus.jsonl](backend/tests/data/line_parse_corpus.jsonl) … 45件のラベル付き実メッセージ相当（制約・症状・多言語・分割・やわらか否定・変更取消を網羅）。基準日は **2026-08-13(木)** に固定。
- ランナー: [backend/scripts/eval_line_parser.py](backend/scripts/eval_line_parser.py)

### 使い方（backend/ で）
```bash
python -m scripts.eval_line_parser              # LLM込みで評価（GEMINI_API_KEYがあれば自動ON）
python -m scripts.eval_line_parser --rules-only # ルールベースのみ（フォールバック健全性の確認）
python -m scripts.eval_line_parser --failures-only
```

### 進め方
1. **改修前にまず1回実行**してベースライン数値を記録（intent検出/date/time の3指標＋失敗ケース数）。
2. タスクB・Cを実装するたびに再実行し、数値が上がることを確認。**下がったらそのコミットは見直す。**
3. ランナーは **intent種別（new/change/cancel）と constraints は現状「未採点」**。タスクB完了でパーサがこれらを produce するようになったら、`_run` の compare 部を拡張して **intent一致・constraint再現率も採点対象に加える**こと（TODOコメント有り）。
4. **実データで育てる**: 本番の `shadow_logs` テーブル（`raw_message` と `analysis_result`）から、実際に来た患者メッセージを抜き出し、正しい期待値を人手で付けて **このJSONLに追記**する。実ログが増えるほど評価の実効性が上がる。目標: まず実ログ100件をコーパス化。
   - 抜き出しSQL例（Render本番DB / 読み取りのみ・PIIは氏名を伏せて扱う）:
     ```sql
     select raw_message, analysis_result, created_at
     from shadow_logs
     order by created_at desc
     limit 200;
     ```

---

## 完了条件（全体）

- [ ] タスクA〜F 実装済み。
- [ ] 評価ランナーの数値がベースライン比で明確に向上（改修前後の数値を PR 説明に記載）。
- [ ] `--rules-only` でも基本ケースが通る＝LLM障害時のフォールバック健全。
- [ ] `pytest`（backend）で、改修前に緑だったテストが緑のまま（既知分離失敗4件を除く）。
- [ ] 🔒原則1〜7 を1つも破っていない（特に `reject_conflicts=True` と対象者ゲート）。
- [ ] 新規追加した parser/composer にユニットテストを追加（少なくとも: 制約抽出、intent分類、polarity、compose_replyのフォールバック）。

---

## 補足: なぜ「パターンを何百個も教える」のが不正解か

人間の言い回しは無限。if-then分岐を足すほど例外の例外が増え、かえって壊れる（今まさにその状態）。
正解は **(1) 理解と生成をLLMに寄せる／(2) few-shotは“コード分岐”ではなく“プロンプト内の例”として与える／(3) 実ログで測って改善する** の3点。
few-shotを増やす作業は「新プロンプトへの例文追加」＋「コーパスへの実ログ追記」で行い、**コードの分岐は増やさない。**
