# 指示書3【最優先・不具合修正】LINE autopilot が「AIの理解結果を捨てて」テンプレを返している

作成: 2026-08-15 / 対象実装者: VS Code Copilot / 対象リポ: `Yoyaku_AppV2`
状態: **本番で会話が成立していない。ユーザー（院長・オーナー）による実機テストで再現済み。**

---

## 実機で起きたこと（再現ログ・これが受け入れ基準）

autopilot 登録済み患者（オーナー）の実際のLINE:

```
Bot : ご希望メニューを選んでください。
患者: いつもので明日できますか？
Bot : ご希望メニューを選んでくださいね。          ← ❌ 完全に無視
患者: いつもの
Bot : ご希望メニューを選んでくださいね。          ← ❌ また無視
患者: [⭐️いつもの（マッスルセラピー 60分・担当: 時田）] ボタンを押す
Bot : ⭐️いつもの内容で承りました（担当: 時田）。ご希望日時を教えてくださいね。例: 明日 10時
患者: 明日！
Bot : ご希望の日時を教えてください。例: 明日の午後3時   ← ❌ 「明日」を無視して同じ質問
```

**患者はボタンを押さないと1ミリも前に進めない。** これは「AI秘書」ではなく、日本語が読めない入力フォーム。

---

## 根本原因（コードで特定済み・憶測ではない）

### 原因1【最重要】LLMの理解結果を計算した直後に捨てている

[backend/app/api/line.py:1265](backend/app/api/line.py) で、autopilot患者のメッセージは**必ずLLMで解析されている**:

```python
parsed_intent = await parse_line_message(text, profile_name=display_name, previous=prev_draft)
```

この時点で「いつもので明日できますか？」は `menu_hint="usual"`, `date=明日` と**正しく解析されているはず**。

ところが `parsed_intent` の使われ方を全走査すると——**`intent`（cancel/change/question）と `needs_human` と `confidence` と、ログ出力にしか使われていない。** `date` / `time` / `menu_hint` / `duration_minutes` は **1箇所も読まれていない。**

そして会話は [line.py:1873](backend/app/api/line.py) の**旧・固定分岐**に落ちる:

```python
if current_mode == "waiting_menu":
    ...
    if text.startswith("⭐️いつもの") and preset:   # ← ボタン文言の完全前方一致のみ
    ...
    selected_menu = await _resolve_menu(db, text)  # ← メニュー名の部分一致のみ
    if not selected_menu:
        await reply_text_with_quick_reply(reply_token, "ご希望メニューを選んでくださいね。", quick_items)
        return
```

**この `waiting_menu` ブロックの中で `parse_line_message` も `parsed_intent` も一度も参照されていない**（1873〜1944行を全走査して確認済み）。
つまり「いつもので明日できますか？」は、⭐️で始まらず、メニュー名とも部分一致しないので、**LLMが正解を出しているのに問答無用でテンプレ**が返る。

> **これが「AIなのにテンプレ」の正体。** LLMを呼ぶ金と時間は払っていて、答えは出ていて、それを使っていない。

### 原因2 autopilotの「いつもの」処理が、必要な場面でだけ無効化されている

[line.py:1291](backend/app/api/line.py):

```python
if is_autopilot_patient and "いつもの" in text and current_mode not in {
    "waiting_menu", "waiting_datetime", "waiting_time_duration", "autopilot_confirm_usual",
}:
```

`waiting_menu` が除外条件に入っている。**「メニューを聞いている最中」こそ「いつもの」と言われる場面**なのに、そこでだけ無効。実機ログの2回目「いつもの」が無視されたのはこれ。

### 原因3 リッチメニューを押した瞬間に旧モードへ固定される

「予約/変更」を押すと `set_user_mode(db, user_id, "waiting_menu")` になる（[line.py:1247](backend/app/api/line.py) 付近）。
**会話の入口で必ず旧ステートマシンに閉じ込められる**ので、以降ずっとテンプレ。実機ログの1行目がまさにこれ。

### 原因4【もう一つの主犯】事実チェックが厳しすぎて、LLMの返事がほぼ全部棄却される

[backend/app/services/line_composer.py:102](backend/app/services/line_composer.py) `_is_grounded_reply`:

```python
factual_keys = ("date", "start", "end", "practitioner", "menu", "duration")
return all(
    str(context[key]) in reply
    for key in factual_keys
    if context.get(key) not in (None, "")
)
```

**context に入っている事実を「一言一句そのまま」含んでいないと棄却→テンプレ差し戻し。**

実機ログの最後がこれ。`ask_datetime` の context には `menu: "マッスルセラピー"` が入っている（[line.py:1992](backend/app/api/line.py)）。
LLMが自然に「明日ですね。何時ごろがご希望ですか？」と書くと、**"マッスルセラピー" という文字列が無いので棄却**され、テンプレ `ご希望の日時を教えてください。例: 明日の午後3時` が出る。

**設計が逆。** 事実チェックは「**でっち上げを防ぐ**」ためのもので、「**全部復唱させる**」ためのものではない。日時を尋ねるだけの文にメニュー名の復唱を強制するのは誤り。

### 原因5 スロット充填が「全部揃うまで無反応」

[line.py:1983](backend/app/api/line.py):

```python
if not merged_dt.get("date") or not merged_dt.get("time"):
    → 同じ「日時を教えて」を繰り返す
```

「明日！」で**日付は取れているのに**、時刻が無いだけで**同じ質問を繰り返す**。
ベテラン事務員なら「明日ですね。何時ごろがご希望ですか？」あるいは「明日ですと 10:00 / 14:30 / 17:00 が空いております」と返す。**取れた情報を認識したと示さない**のが、患者に「通じてない」と感じさせる決定打。

---

## 🔒 守る原則（変更禁止）

1. `create_reservation(..., reject_conflicts=True)` を**絶対に外さない**（無人で競合枠に重ねない）。
2. 対象者ゲート（`settings.line_autopilot_enabled` ＋ `patients.line_autopilot_enabled` ＋ `#autopilot-setup`）を変えない。
3. **autopilot対象外の患者・shadow経路の挙動は1バイトも変えない。** 旧 `waiting_menu` / `waiting_time_duration` / `waiting_datetime` の分岐は**非autopilot患者のために残す**（消さない）。
4. LLM失敗時は必ずテンプレへフォールバック（機能が死なない）。
5. PII（電話番号・生年月日）をLLMへ送らない既存のマスキングを維持。
6. 既存テストを緑のまま（`test_shadow_mode.py` / `test_line_ai_secretary.py`）。

---

## タスク1【最優先】autopilot患者は「LLM主導のスロット充填」に一本化する

### 考え方
autopilot患者にとって `current_mode` は **「次に何を聞くべきかのヒント」であって、入力を検閲する門ではない。**
どのモードにいても、**毎メッセージ `parsed_intent` を draft にマージし、足りないものだけ聞く。**

### 実装
1. `is_autopilot_patient` が True の場合、[line.py:1873](backend/app/api/line.py) 以降の旧 `waiting_menu` / `waiting_time_duration` / `waiting_datetime` 分岐に **入らないようにする**（各 `if` に `and not is_autopilot_patient` を付ける等）。旧分岐は非autopilot患者用にそのまま残す。
2. autopilot用の**統合スロット充填**を1本用意し、モードに関係なく毎メッセージ実行する:
   - `parsed_intent` から `date` / `time` / `duration_minutes` / `menu_hint` / `constraints` を **draft へマージ**（`merge_user_draft`）。
   - `menu_hint == "usual"`（および本文に「いつもの」「前回と同じ」「この前と同じ」）→ `_get_patient_default_preset` を引いて menu/duration/practitioner を draft に入れる。**モードによる除外はしない**（原因2の除外条件を削除）。
   - `menu_hint` が実メニュー名 → `_resolve_menu` で解決して draft へ。
   - ボタン文言（`⭐️いつもの…`、メニュー名、`○○分`）も**従来どおり受理**する（ボタン利用者を壊さない）。
3. **揃ったものから順に前進**し、足りない項目だけ尋ねる:
   - menu 未定 → `ask_menu`（クイックリプライは維持）
   - menu 済 & date 済 & time 未定 → **`ask_time_for_date`**（新規 situation。後述タスク3）
   - menu 済 & date 未定 → `ask_datetime`
   - 全部揃った → 既存の空き確認 → `confirm_slot` / `offer_alternatives` / 即確定（既存ロジックをそのまま使う）
4. リッチメニュー「予約/変更」押下時（原因3）は、autopilot患者では **`waiting_menu` に固定しない**。draft をクリアして「ご用件をどうぞ（メニュー選択のクイックリプライ付き）」の状態にし、**次の自由文が必ずLLM解析される**ようにする。

### 完了条件
- 「いつもので明日できますか？」1通で、**menu=いつもの内容 + date=明日** が draft に入る。
- ボタンを一度も押さずに予約が完了できる。

---

## タスク2【最優先】`_is_grounded_reply` を「復唱の強制」から「捏造の防止」へ

対象: [backend/app/services/line_composer.py](backend/app/services/line_composer.py)

1. **situation ごとに「復唱が必須なキー」を定義**する。全 `factual_keys` を一律必須にしない。
   - **必須（数値の取り違えが事故になる場面）**: `confirmed` / `change_done` / `confirm_slot` → `date`, `start`, `practitioner` は verbatim 必須（`end`・`menu` は任意＝含んでいなくても棄却しない）。
   - `cancel_done` → `date`, `start` を必須。
   - `offer_alternatives` → 各候補の `label` は verbatim 必須（番号と枠がズレると事故）。
   - **不要（尋ねるだけの場面。棄却しない）**: `ask_datetime` / `ask_time_for_date` / `ask_menu` / `ask_missing` / `parse_failed` / `handoff_to_human` / `slot_taken` / `reconfirm_yes_no`。
2. 代わりに**捏造チェック**を入れる: 返信文に `\d{1,2}:\d{2}` や `\d{1,2}月\d{1,2}日` 等の日時表現が現れた場合、それが **context 内の値と一致しない**なら棄却→フォールバック。
   （＝「context に無い日時を勝手に作った」だけを弾く。context の値を復唱しないことは許す。）
3. 棄却が起きたら `logger.info` に **situation・棄却理由・LLM原文** を残す（次の調査のため）。

### 完了条件
- 「明日ですね。何時ごろがご希望ですか？」のような**メニュー名を含まない自然文が棄却されない**。
- 「8/20 14:00」を context に無いのに書いた返信は棄却される。

---

## タスク3 「取れた情報を認識したと示す」返信にする

1. 新 situation **`ask_time_for_date`** を追加（`SITUATION_GUIDES` とフォールバック文も）。
   - 目的: 「日付は受け取った。時刻だけ聞く」。
   - context: `date_label`(例 `8/16(土)`), `menu`, `duration`, `available_times`(その日の空き時刻の配列), `patient_message`。
   - フォールバック文例: `8/16(土) ですね。何時ごろがご希望ですか？（空き: 10:00 / 14:30 / 17:00）`
2. **その日の空き時刻を実際に出す**: date が確定して time 未定のとき、既存の候補生成（`build_same_day_candidates` / `score_candidates`）で**その日の空き枠を最大3つ**取得し、`available_times` として渡す。
   - 空きが無ければ「その日は満席」と伝えて別日を促す。
   - ⚠️ ここで予約は作らない。**提示のみ**。
3. 同様に、time だけ取れて date 未定なら「◯時ですね。何日がご希望ですか？」と返す。

### 完了条件
- 「明日！」→ 「明日（8/16）ですね。何時ごろがご希望ですか？ 空き: …」と**日付を復唱して**時刻だけ聞く。同じ質問の繰り返しが消える。

---

## タスク4 本番でLLMが実際に動いているかの確認（設定漏れの切り分け）

**この確認を最初に行うこと。** 未設定なら以降の実装効果はゼロに見える。

1. `render.yaml` は `GEMINI_API_KEY` を `sync: false` で宣言している＝**値はRenderダッシュボードで手入力が必須**。値が未設定だと `compose_reply` も `parse_line_message` も**全てフォールバック＝全部テンプレ**。
   - **オーナー作業**: Renderダッシュボードで本番サービスの `GEMINI_API_KEY` に実値が入っているか確認（Copilotはアクセス不可）。
2. コード側で切り分け可能にする: 起動時に一度だけ、`GEMINI_API_KEY` の**有無**（値そのものは絶対に出さない）と `gemini_model` を `logger.info` で出力する。
   例: `LINE autopilot LLM config: api_key=SET model=gemini-3.1-flash-lite`
3. `compose_reply` / `parse_line_message` がフォールバックした際、**理由**（キー未設定 / HTTPエラー / JSON不正 / grounded棄却）を `logger.warning` に区別して出す。本番ログを見れば「なぜテンプレなのか」が即分かる状態にする。

---

## 検証（必須・これを通さずに完了報告しない）

### A. 再現シナリオの自動テスト（新規追加）
実機ログと**同じ順序**を再生するテストを `tests/test_line_ai_secretary.py` に追加する。LLMはモックでよいが、**モックは「正しく解析できた場合」の値を返す**こと（`menu_hint="usual"`, `date=明日` 等）。

1. `waiting_menu` 状態で `いつもので明日できますか？` を受信
   → **「メニューを選んでください」を返さない**こと（アサート）
   → draft に menu（いつもの内容）と date（明日）が入ること
2. `waiting_datetime` 状態で `明日！` を受信
   → 返信に**日付の復唱が含まれる**こと、かつ `ご希望の日時を教えてください` の丸投げテンプレでないこと
3. ボタン（`⭐️いつもの（…）` / メニュー名）でも従来どおり動くこと（後方互換）

### B. LLM実測
```bash
python -m scripts.eval_line_parser --sleep 1.5
```
`LLM実効件数` が 40/45 以上であること（0ならAPI未設定＝タスク4へ戻る）。

### C. 回帰
```bash
python -m pytest tests/test_shadow_mode.py tests/test_line_ai_secretary.py -q
```
既存分＋新規分がすべて緑。

### D. 安全確認（機械的に）
- `reject_conflicts=True` が autopilot 確定経路すべてに残っている。
- 対象者ゲート（グローバル＋患者個別）が無傷。
- 非autopilot患者の旧分岐が**そのまま残っている**。

---

## 完了条件

- [ ] タスク4でLLM設定状況がログで判別可能。本番キー有無をオーナーが確認済み。
- [ ] **ボタンを一度も押さずに**「いつもので明日の14時」から予約確定まで到達できる。
- [ ] 「いつもので明日できますか？」に「メニューを選んでください」と返さない。
- [ ] 「明日！」に日付を復唱して時刻だけ尋ねる（同じ質問の繰り返しゼロ）。
- [ ] `_is_grounded_reply` が situation 別になり、尋ねる系の自然文が棄却されない。
- [ ] 検証A/B/C/D すべて通過。数値と再現テスト結果をPR説明に記載。
- [ ] 🔒原則1〜6 無傷。

---

## Copilotへの一言（コピペ用）

```
リポジトリ直下の INSTRUCTIONS_LINE_AUTOPILOT_FIX_ROUTING_20260815.md を読んで修正して。
これは新機能ではなく「実機で会話が成立していない不具合」の修正。
最大の問題は、line.py:1265 でLLMが解析した parsed_intent の date/time/menu_hint を
どこでも使っておらず、line.py:1873 の旧 waiting_menu 分岐（ボタン完全一致のみ）が
テンプレを返していること。タスク4→1→2→3の順で対応。
検証Aの再現テスト（ボタンを押さずに会話が進むこと）を必ず追加して通すこと。
🔒原則（reject_conflicts=True維持・対象者ゲート不変・非autopilot経路は変更しない・フォールバック健全）は厳守。
```
