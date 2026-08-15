# 指示書2: LINE autopilot の「声」を完成させ、意味不明な会話を直す

作成: 2026-08-13 / 対象実装者: VS Code Copilot / 対象リポ: `Yoyaku_AppV2`
前提: 指示書1 `INSTRUCTIONS_LINE_AUTOPILOT_UPGRADE_20260813.md`（A〜F）は実装済み。本書はその **Task D の積み残し** と **会話破綻** の修正に特化する。

---

## 背景（いま何が起きているか）

課金（Gemini プリペイド残高）は復活済み。にもかかわらず、登録済み患者（院長・オーナー）との autopilot 会話が **①テンプレのまま ②時々意味不明** になる。
コードを追った結果、原因は明確：

**「理解」はLLM化されたが、「話し方（返信文）」がほぼ全部ハードコードのテンプレのままだから。**

- autopilot 流路の患者向け返信は約45箇所。うち `compose_reply`（LLM生成）はたった **4箇所** だけ。
  - [line.py:1029](backend/app/api/line.py) `handoff_to_human` … **context が `{}`（空）**
  - [line.py:1600](backend/app/api/line.py) `ask_datetime` … **context が `{}`（空）**
  - [line.py:1697](backend/app/api/line.py) `parse_failed` … **context が `{}`（空）**
  - [line.py:1830](backend/app/api/line.py) `confirmed` … これだけ実contextあり（唯一まともにAIが喋る）
- 会話の山場である **「この枠でよろしいですか」「候補①②③」「いつものでよろしいですか」** は全部ハードコード（`_format_autopilot_slot_confirmation` / `_compose_alternatives_text` / `_format_usual_confirmation`）。
- 空 `{}` で渡している3箇所は、LLMに事実が何も渡らないので**generic or 的外れな文**になり得る＝「意味不明」の一因。

---

## 🔒 守る原則（指示書1と同じ・厳守）

1. 予約確定の判断はコードが持つ。`create_reservation(..., reject_conflicts=True)` を**絶対に外さない**（無人で競合枠に重ねない）。
2. 対象者ゲート（`settings.line_autopilot_enabled` ＋ `patients.line_autopilot_enabled` ＋合言葉 `#autopilot-setup`）を変えない。`is_autopilot_patient` 判定はそのまま。
3. autopilot 対象外の患者フロー（shadow等）は1バイトも変えない。
4. **LLMは必ずフォールバックを持つ。** `compose_reply` はLLM失敗時に必ず既存テンプレ文を返す契約を維持（現状の `_fallback` を壊さない）。
5. LLMに渡すのは本文・表示名・確定した予約事実まで。カルテ番号/電話/生年月日はプロンプトに載せない。
6. 既存テスト（`test_shadow_mode.py` / `test_line_ai_secretary.py`）を緑のまま保つ。

---

## タスク0 — 先に健全性チェック（5分）

「LLMが本番/ローカルで本当に効いているか」を先に確定する。ここが×だと以降の修正効果がゼロに見える。

1. 単発プローブでGeminiがOKか確認（backend/ で）:
   ```bash
   python -c "import httpx,os;from app.config import settings;r=httpx.post(f'https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent',headers={'x-goog-api-key':settings.gemini_api_key},json={'contents':[{'role':'user','parts':[{'text':'say ok'}]}]},timeout=30);print(r.status_code,r.text[:300])"
   ```
   - `200` かつ本文に応答があればOK。`429 RESOURCE_EXHAUSTED` ならまだ残高問題→実装を進めても無駄。
2. 評価ランナーで「LLM実効件数」を確認:
   ```bash
   python -m scripts.eval_line_parser --sleep 1.5
   ```
   先頭に出る `LLM実効件数: X/45` が **0/45 なら全フォールバック**（＝まだLLMが効いていない）。ここが 40/45 以上になって初めて数値がLLMの実力。
3. 本番Render側にも `GEMINI_API_KEY` と `LINE_AUTOPILOT_ENABLED=true` が入っているか（ローカルだけ設定されていて本番に無い、が頻出）。`gemini_model` の値（`gemini-3.1-flash-lite`）がそのキーで叩けることも1で確認済みなら合格。

---

## タスクD-1 — compose_reply を「事実を喋る」実装に強化

対象: [backend/app/services/line_composer.py](backend/app/services/line_composer.py)

現状の `compose_reply` は situation別のガイドが弱く、context前提の文言例も無い。以下へ強化する。

1. **situation ごとの生成ガイド**を用意（下記「situation 一覧」参照）。プロンプトに「この状況で何を伝えるべきか」を1〜2行で明示し、**context の各キーの意味**も添える。
2. **事実の厳守を強制**: 「context に無い日時・空き・診療内容を作らない。日時・担当名・番号・メニュー名は context の値をそのまま使う。」
3. **患者の直前メッセージを context に含めて渡す**（`patient_message` キー）。これで「腰がつらくて」に対し「お腰おつらいですね」と**受け止めてから**本題に入れる＝会話が噛み合う。ただし医療指示（湿布・安静等）は禁止をプロンプトで明示。
4. **短さ・トーン**: 敬語・1〜3文・絵文字最大1・1メッセージ1論点。
5. **技術的修正**: `httpx.AsyncClient()` を `async with httpx.AsyncClient() as client:` に（現状コネクションリーク）。`timeout` 継続。例外時は必ず `_fallback` を返す契約維持。
6. **フォールバック文（`_fallback`）も context を反映**できる範囲で自然文に（例: `confirm_slot` は context に日時・担当があれば埋め込む）。LLMが落ちても最低限の情報は出す。

### compose_reply プロンプト骨子（強化版）
````text
あなたは接骨院の受付ベテラン事務員です。患者へのLINE返信を作ります。
必ず守る:
- 下の「確定事実」に無い日時・空き状況・診療内容を新たに作らない。日時/担当名/番号/メニュー名は確定事実の値をそのまま使う。
- 敬語で簡潔に。1〜3文。絵文字は最大1つ。1メッセージ1論点。
- 医療的な指示・診断はしない（「湿布を」「安静に」等は書かない）。痛みには一言いたわる程度に留める。
- 患者の直前メッセージ(patient_message)があれば、まず一言受け止めてから本題に入る。
状況(situation)ごとの目的:
{situation_guide}
状況: {situation}
確定事実(JSON): {context_json}
返信文だけを返す:
````

---

## タスクD-2 — 全ての患者向け返信を compose_reply（実context）へ接続

対象: [backend/app/api/line.py](backend/app/api/line.py) の autopilot 流路（`is_autopilot_patient` 分岐内）。

**方針**: autopilot 経路の `reply_to_line(reply_token, "固定文字列")` を、原則すべて `reply_to_line(reply_token, await compose_reply(situation, context))` に置換する。
`reply_text_with_quick_reply`（ボタン付き）は **items（ボタン）はそのまま**、**テキスト部分だけ** compose_reply に置換してよい。

### 置換対象と situation/context の対応表（主要なもの）

| 現状の箇所(目安行) | 現在のテンプレ | situation | 渡す context（事実） |
|---|---|---|---|
| slot確認 `_format_autopilot_slot_confirmation`（[line.py:1787](backend/app/api/line.py) 等） | 「この日時でよろしいですか」 | `confirm_slot` | patient_name, date, start, end, practitioner, menu, first_visit_note, patient_message |
| 候補提示 `_compose_alternatives_text`（[line.py:1794](backend/app/api/line.py)） | 「候補①②③…番号で」 | `offer_alternatives` | alternatives[](各 label/date/start/end/practitioner), vague(bool), first_visit_note, patient_message |
| いつもの確認 `_format_usual_confirmation`（[line.py:1282](backend/app/api/line.py) / [1633](backend/app/api/line.py)） | 「いつもの○○でよろしいですか」 | `usual_confirm` | menu, duration, practitioner, patient_message |
| 日時を聞く（[line.py:1600](backend/app/api/line.py) の空`{}`を修正） | 「ご希望日時を教えて」 | `ask_datetime` | patient_name, menu, symptom, patient_message |
| 不足項目（`_build_missing_info_message` [line.py:1663](backend/app/api/line.py)） | 「○○を教えて」 | `ask_missing` | missing_fields[], 既知のdraft, patient_message |
| 予約確定（[line.py:1097](backend/app/api/line.py) のハードコード版も） | 「確定しました」 | `confirmed` | date, start, end, practitioner, menu |
| キャンセル完了（[line.py:1177](backend/app/api/line.py)） | 「キャンセルしました」 | `cancel_done` | date, start, practitioner |
| 変更完了（[line.py:1240](backend/app/api/line.py)） | 「変更しました」 | `change_done` | start, end, practitioner |
| 枠が直前に埋まった（[line.py:1091](backend/app/api/line.py)/[1140](backend/app/api/line.py)/[1235](backend/app/api/line.py)） | 「直前に埋まりました」 | `slot_taken` | patient_message |
| 手動退避（[line.py:1029](backend/app/api/line.py) 空`{}`/[1008](backend/app/api/line.py)） | 「担当者が確認中です」 | `handoff_to_human` | reason, patient_message |
| 解析失敗（[line.py:1697](backend/app/api/line.py) 空`{}`） | 「聞き取れませんでした」 | `parse_failed` | patient_message |
| はい/いいえ再促し（[line.py:1069](backend/app/api/line.py)/[1186](backend/app/api/line.py)/[1226](backend/app/api/line.py)） | 「はい/いいえで返信を」 | `reconfirm_yes_no` | what（何を確認しているか）, patient_message |

> 注: `confirm_slot` / `offer_alternatives` / `usual_confirm` の3つが**体感インパクト最大**。ここを最優先で実context接続する。
> ボタン付きメニュー選択（`_build_menu_quick_reply_items` を伴う箇所）は、テキストだけ `ask_menu` で自然文にし、ボタンは維持。

### situation 一覧（`situation_guide` に入れる目的文の例）
- `confirm_slot`: 提示した日時・担当で良いか、一言添えて確認する。
- `offer_alternatives`: 希望が満席なので、番号付き候補を分かりやすく並べ、番号で選べると伝える。
- `usual_confirm`: いつものメニュー内容を提示し、これで良いか確認する。
- `ask_datetime`: 症状があれば受け止めた上で、希望日時を尋ねる。
- `ask_missing`: 足りない項目だけを、責めずに1つ尋ねる。
- `confirmed` / `cancel_done` / `change_done`: 完了を告げ、来院を歓迎する（変更/取消は事実のみ）。
- `slot_taken`: 直前に埋まったことを詫び、別候補/別日時へ促す。
- `handoff_to_human`: 無人で完結できない旨を丁寧に伝え、担当者対応になると案内。
- `parse_failed`: 聞き取れなかったことを詫び、例を添えて言い直しを促す。
- `reconfirm_yes_no`: 何に対する はい/いいえ かを明示して促す。

---

## タスクD-3 — 「意味不明な会話」の原因特定と修正

テンプレ以外に会話が破綻する要因を潰す。**まず実際の破綻例を捕まえてから直す**（憶測で直さない）。

1. **実ログで破綻例を捕捉**: 一時的に、autopilot 経路で「受信本文 / パーサ出力(intent,date,time,polarity,confidence,needs_human,constraints) / 選ばれた situation / 送信した返信文」を1行ログに出す（`logger.info`）。院長・オーナーで数パターン（新規/変更/取消/いつもの/満席）を実機で送り、**どこで噛み合わなくなるか**を特定する。`shadow_logs` の `raw_message`/`analysis_result` も参照。
2. **想定される破綻と対策**:
   - **空context由来の的外れ返信** → タスクD-2で解消（実context化）。
   - **debounce(Task A)が無関係な連投を1つに融合** → 融合の時間窓・条件を見直し、意図の異なる連投（例: 予約途中に「ありがとう」）は融合しない。
   - **intent誤分類でモード遷移が飛ぶ** → `confidence:low` または `needs_human:true` のときは、**確定・提案に進まず素直に聞き返す or 手動退避**（無理に進めない）。ガードを入れる。
   - **確認モード中の自由文** → `autopilot_*_confirm` 中に「はい/いいえ」でない自由文（例: 「やっぱり別の日」）が来たら、`polarity`/intent を見て**適切なモードへ戻す**（現状は再促しループになりがち）。
   - **同一メッセージに複数意図**（「いつもので、あと領収書ほしい」）→ 予約は進めつつ `needs_human` を立てて管理者に申し送り。
3. **ループ防止**: 同じ situation の聞き返しが連続3回続いたら、`handoff_to_human` に落として管理者へ通知（ベテラン事務員も「これは電話で」と切り替える）。

---

## タスクD-4 — 確認往復をもう一段減らす（任意・体感向上）

- 既知患者が1メッセージで「メニュー＋日時」を言い切り、`confidence:high` かつ空き枠が取れる場合は、`confirm_slot` を挟まず即 `confirmed`（`reject_conflicts=True` は維持）。指示書1のタスクEの延長。
- 新規・`confidence:low`・初回は従来どおり1回確認を残す（安全側）。

---

## 検証（必須）

1. **LLM実効の確認**: `python -m scripts.eval_line_parser --sleep 1.5` で `LLM実効件数` が 40/45 以上、かつ intent種別/日付/時刻/制約 が指示書1のベースライン（意図37/45・制約23/45 等）より**明確に向上**していること。数値をPR説明に貼る。
2. **実機シナリオ**（院長・オーナーのautopilot登録済みアカウントで）:
   - 新規: 「肩こりがつらくて明日の午後行きたい」→ 症状を受け止め→枠 or 候補→確定まで自然に。
   - いつもの: 「いつもので土曜の夕方」→ usual確認 or 即提示→確定。
   - 満席: 埋まっている枠を狙って→候補①②③→番号で確定。
   - 変更: 「明日の予約、明後日の午後に変えたい」→ 変更候補→確定。
   - 取消: 「明日キャンセルで」→ 確認→完了。
   - 各返信が**テンプレ臭くなく、事実は正確**であること（日時・担当・メニューが実際の予約と一致）。
3. **回帰**: `pytest tests/test_shadow_mode.py tests/test_line_ai_secretary.py -q` が緑。
4. **安全**: `reject_conflicts=True`・対象者ゲート・フォールバックの3点が無傷。競合枠に自動確定していないこと（実機で満席枠を狙って確認）。

---

## 完了条件

- [ ] タスク0でLLMが本番/ローカル両方で 200 応答することを確認済み。
- [ ] `confirm_slot` / `offer_alternatives` / `usual_confirm` を含む主要返信が compose_reply（実context）経由。空 `{}` の3箇所を解消。
- [ ] 実機シナリオ5種が自然かつ事実正確に完了。
- [ ] `LLM実効件数` が 40/45 以上で、精度がベースライン超え（数値記載）。
- [ ] 既存テスト緑・🔒原則1〜6 無傷。
- [ ] 「意味不明」破綻の再現例と、その修正（D-3のガード）をPRに記載。

---

## Copilotへの一言（コピペ用）

```
リポジトリ直下の INSTRUCTIONS_LINE_AUTOPILOT_VOICE_20260813.md を読んで、タスク0→D-1→D-2→D-3→（任意D-4）の順に実装して。
まずタスク0でGeminiが200を返すことと LLM実効件数を確認。次に compose_reply を実context化し、confirm_slot/offer_alternatives/usual_confirm を最優先で接続。
🔒原則（reject_conflicts=True維持・対象者ゲート不変・フォールバック健全）は厳守。各段階で eval と pytest を回して数値を記録。
```
