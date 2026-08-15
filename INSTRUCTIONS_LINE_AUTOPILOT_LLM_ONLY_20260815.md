# 指示書4【最優先・これが唯一の正】LINE autopilot は「LLMが読み、LLMが書き、そのまま送る」

作成: 2026-08-15 / 対象実装者: VS Code Copilot / 対象リポ: `Yoyaku_AppV2`
**本書は指示書1〜3のうち、返信生成に関する記述をすべて上書きする。矛盾したら本書が優先。**

---

## 0. この改修の唯一の目的

> **患者のメッセージを LLM が読む → LLM が自然な返信文を書く → その文をそのまま送る。**

これだけ。**定型文（テンプレ）で返すのは、外部APIが完全に死んでいるときの非常口のみ**であり、通常運用では1通も出してはならない。

### なぜ今これを直すのか（現状の誤り）

過去の指示（指示書2 D-1「日時・担当名は context の値をそのまま使う」）を、実装side が
「**LLMの返信に事実が一言一句含まれていなければ、その返信を捨ててテンプレに差し替える**」
と解釈し、[backend/app/services/line_composer.py](backend/app/services/line_composer.py) に `_is_grounded_reply` を実装した。

その結果:
- 日時を尋ねるだけの場面でも context の `menu`（例: マッスルセラピー）の**復唱を強制**され、
  LLMが自然に書いた「明日ですね。何時ごろがご希望ですか？」が**棄却されテンプレに戻る**。
- 実機で「AIなのに全部テンプレ」という状態になった。

**この「棄却してテンプレ差し替え」という設計自体が誤り。本書で全廃する。**

---

## 1. 🔒 絶対に壊してはいけないもの（スコープ厳守）

現在この予約システムは、**全患者にスタッフが手打ちで返信している運用**である。今回の自動化は**本番運用の裏で、ごく一部の人だけで試すテスト**である。

1. **対象者は「合言葉 `#autopilot-setup` で登録を完了した患者」だけ。** 判定は現行のまま:
   `settings.line_autopilot_enabled`（グローバル）＋ `patients.line_autopilot_enabled`（患者個別）＋ `is_autopilot_patient`。
   **この条件を緩めない・広げない・自動付与しない。**
2. **autopilot 対象外の患者の挙動は 1バイトも変えない。** 旧 `waiting_menu` / `waiting_time_duration` / `waiting_datetime` の分岐や shadow 経路は**そのまま残す**（対象外患者が今まで通り動くために必要）。本書の変更はすべて `is_autopilot_patient == True` の内側にのみ適用する。
3. `create_reservation(..., reject_conflicts=True)` を**絶対に外さない**（無人で競合枠に予約を重ねない）。
4. PII（電話番号・生年月日）のLLM送信前マスキングを維持。
5. 既存テスト（`test_shadow_mode.py` / `test_line_ai_secretary.py`）を緑のまま。

---

## 2. タスクA【最重要】`_is_grounded_reply` による「テンプレ差し替え」を全廃する

対象: [backend/app/services/line_composer.py](backend/app/services/line_composer.py)

### やること

1. **`_is_grounded_reply` による棄却→テンプレ差し替えを削除する。** LLMが返した文は**原則そのまま送信する。**
2. 事実の正しさは「復唱の強制」ではなく「**矛盾の検出と作り直し**」で担保する:
   - 返信文に日付・時刻の表現（`\d{1,2}:\d{2}` / `\d{1,2}時` / `\d{1,2}/\d{1,2}` / `\d{1,2}月\d{1,2}日` 等）が含まれる場合、
     それが **context に渡した事実と矛盾していないか**だけを見る。
   - **矛盾していた場合のみ、1回だけ作り直しを依頼する**（同じプロンプトに
     「前回の返信は事実と異なる日時を含んでいた。context の値だけを使って書き直せ」を追記して再生成）。
   - 作り直しても矛盾する場合に限り、テンプレへ落として `logger.error` + 管理者へ通知。
   - **context に無い日時を「書いていない」ことは何の問題もない。棄却理由にしない。**
3. **テンプレ（`_fallback`）が使われるのは以下の場合だけ**にする:
   - Gemini API がエラー/タイムアウト/キー未設定（＝通信不能）
   - 上記2の作り直しにも失敗
   いずれの場合も **`logger.error` に理由を明記**し（`reason=api_error` / `reason=contradiction`）、
   管理者LINEへ「AI返信に失敗したためテンプレで応答した」旨を通知する（**テンプレが出たら異常事態として可視化する**）。
4. `compose_reply` は `situation` と `context` に加えて、**会話の直近履歴（直近3往復程度）** を context に含めて渡す。
   自然な会話には文脈が要る。履歴は `line_user_states.context_data` に保持する。

### プロンプト（`compose_reply`）はこの方針で書き直す

````text
あなたは接骨院の受付を長年担当しているベテラン事務員です。患者へのLINE返信を、あなた自身の言葉で自然に書いてください。

【あなたの役割】
患者の言葉をそのまま受け止め、必要なことだけを、感じよく、短く伝える。機械的な定型文は書かない。

【厳守】
- 下の「確定事実」に無い日時・空き状況・診療内容を**新たに作らない**（事実の捏造だけが禁止事項）。
- 確定事実にある日時・担当名・メニュー名に言及するときは、その値を正確に使う（言及しないこと自体は自由）。
- 敬語。1〜3文。絵文字は最大1つ。1メッセージ1論点。
- 医療的な指示・診断はしない（「湿布を」「安静に」等は書かない）。痛みには一言いたわる程度。
- 患者の直前メッセージがあれば、まず一言受け止めてから本題に入る。
- 「はい/いいえ」で答えてほしいときは、そう分かるように書く。

【状況】{situation}: {situation_guide}
【直近の会話】{recent_history}
【確定事実(JSON)】{context_json}

返信文だけを出力:
````

### 完了条件
- LLMが正常に応答している限り、**テンプレ文字列が患者に送られることが無い**。
- 「明日ですね。何時ごろがご希望ですか？」のような、事実を復唱しない自然文が**そのまま送られる**。

---

## 3. タスクB【最重要】LLMの理解結果を実際に使う（現在は捨てている）

[backend/app/api/line.py:1265](backend/app/api/line.py) で autopilot 患者のメッセージは毎回 LLM 解析され `parsed_intent` に入る。
しかし `parsed_intent` の `date` / `time` / `menu_hint` / `duration_minutes` は**どこでも読まれていない**（全走査で確認済み）。
会話は [line.py:1873](backend/app/api/line.py) の旧 `waiting_menu` 分岐に落ち、そこは
「`⭐️` で始まるボタン文言の完全一致」か「メニュー名の部分一致」しか受け付けないため、
「いつもので明日できますか？」が**問答無用でテンプレ**になっていた。

### やること

1. **autopilot 患者は、旧 `waiting_menu` / `waiting_time_duration` / `waiting_datetime` 分岐に入らせない**
   （各 `if` に `and not is_autopilot_patient` を追加。旧分岐は対象外患者用に温存＝🔒原則2）。
2. autopilot 用の**統合スロット充填**を1本作り、**モードに関係なく毎メッセージ実行**する:
   - `parsed_intent` の `date` / `time` / `duration_minutes` / `menu_hint` / `constraints` を **draft へマージ**。
   - `menu_hint == "usual"` または本文に「いつもの」「前回と同じ」「この前と同じ」→ `_get_patient_default_preset` を適用。
     **[line.py:1291](backend/app/api/line.py) の `current_mode not in {"waiting_menu", ...}` という除外条件は削除する**
     （「メニューを聞いている最中」こそ「いつもの」と言われる場面であり、そこで無効なのは誤り）。
   - `menu_hint` が実メニュー名 → `_resolve_menu` で解決して draft へ。
   - **ボタン文言（`⭐️いつもの…` / メニュー名 / `○○分`）も従来どおり受理**する（ボタン派を壊さない）。
3. **揃った情報から前進し、足りないものだけ尋ねる**（すべて LLM 生成文で）:
   - menu 未定 → `ask_menu`（クイックリプライのボタンは維持してよい。**文面はLLM**）
   - menu 済・date 済・time 未定 → `ask_time_for_date`（**その日の空き時刻を最大3件 context に入れて提示させる**）
   - date 未定 → `ask_datetime`
   - 全部揃った → 既存の空き確認 → `confirm_slot` / `offer_alternatives` / 即確定（**予約ロジックは既存のまま**）
4. リッチメニュー「予約/変更」押下時、autopilot 患者では **`waiting_menu` に固定しない**。
   draft をクリアして、次の自由文が必ず LLM 解析される状態にする。

### 完了条件
- 「いつもので明日できますか？」**1通**で、menu（いつもの内容）と date（明日）が draft に入る。
- **ボタンを一度も押さずに**予約確定まで到達できる。

---

## 4. タスクC 残っているハードコード返信を全て LLM 生成へ

autopilot 経路に、まだ `compose_reply` を通さず固定文を送っている箇所が残っている。**以下をすべて LLM 生成に置換する**
（`reply_text_with_quick_reply` の**ボタンは維持、テキストのみ**置換）:

| 行 | 現在の固定文 | 割り当てる situation |
|---|---|---|
| [1249](backend/app/api/line.py) | 担当者が内容を確認中です… | `handoff_to_human` |
| [1493](backend/app/api/line.py) | キャンセル処理を完了できませんでした… | `cancel_failed` |
| [1517](backend/app/api/line.py) | キャンセルを取りやめました。 | `cancel_aborted` |
| [1538](backend/app/api/line.py) | 変更する予約を確認できませんでした… | `change_target_missing` |
| [1571](backend/app/api/line.py) | 変更候補を取りやめました… | `change_aborted` |
| [1575](backend/app/api/line.py) | 変更する場合は「はい」… | `reconfirm_yes_no` |
| [1614](backend/app/api/line.py) / [1643](backend/app/api/line.py) | ご希望メニューを選んでください。 | `ask_menu` |
| [1728](backend/app/api/line.py) | 確認のため、フルネームを… | `ask_full_name` |
| [1828](backend/app/api/line.py) | 確認情報が見つからないため… | `identity_retry` |
| [1907](backend/app/api/line.py) | ⭐️いつもの内容で承りました… | `usual_accepted` |
| [1914](backend/app/api/line.py) | ご希望メニューを選んでくださいね。 | `ask_menu` |
| [1951](backend/app/api/line.py) | 先にメニューを選んでください。 | `ask_menu` |
| [1969](backend/app/api/line.py) | ありがとうございます。続いてご希望日時を… | `ask_datetime` |

> ⚠️ [1728](backend/app/api/line.py) / [1828](backend/app/api/line.py) は本人確認フロー。**LLMへ渡す前のPIIマスキングを必ず維持**すること（🔒原則4）。
> ⚠️ 上表のうち、対象外患者も通り得る箇所は **`is_autopilot_patient` の場合のみ LLM 生成**とし、対象外患者には現行の固定文をそのまま返す（🔒原則2）。

新しい `situation` は `SITUATION_GUIDES` に目的を1行で追記し、対応するフォールバック文（非常口用）も用意する。

---

## 5. タスクD 「受け取った情報を認識したと示す」

現状 [line.py:1983](backend/app/api/line.py) は date と time が**両方揃うまで同じ質問を繰り返す**。
実機で「明日！」に対し「ご希望の日時を教えてください」と返したのはこれ。

- date だけ取れた → 「**明日（8/16）ですね。**何時ごろがご希望ですか？」と**日付を認識したと示して**時刻だけ聞く。
  さらに `build_same_day_candidates` 等でその日の空き時刻を最大3件取得し context に渡して**具体的に提示**させる。
  （⚠️ ここでは予約を作らない。提示のみ。空きが無ければ「その日は満席」と伝えて別日を促す。）
- time だけ取れた → 「◯時ですね。何日がご希望ですか？」
- 同じ質問を2回連続で投げない。

---

## 6. 検証（これを通さずに完了報告しない）

### A. 「テンプレ禁止」テスト（新規・最重要）
`_fallback` が返す既知のテンプレ文字列を定数として持ち、**LLMが正常応答している条件下で、患者への返信がそのテンプレ文字列と一致したら失敗**とするテストを追加する。
（LLMはモックし、自然文を返すよう設定。テンプレが出る＝配線漏れとして検出できる状態にする。）

### B. 実機ログ再現テスト（新規・受け入れ基準）
以下を**この順序**で再生するテストを追加する。LLMモックは「正しく解析できた場合」の値を返す:

1. `waiting_menu` 状態で `いつもので明日できますか？`
   → 「メニューを選んでください」系を返さない／draft に menu と date（明日）が入る
2. `waiting_datetime` 状態で `明日！`
   → 返信に日付の認識が含まれる／同じ質問の丸投げにならない
3. ボタン（`⭐️いつもの（…）` / メニュー名）でも従来どおり動く（後方互換）

### C. スコープ死守テスト
- `line_autopilot_enabled=False` の患者は**従来の固定文フローのまま**であること（LLM生成に変わっていないこと）をテストで固定する。

### D. LLM実測 & 回帰
```bash
python -m scripts.eval_line_parser --sleep 1.5
python -m pytest tests/test_shadow_mode.py tests/test_line_ai_secretary.py -q
```

### E. 安全確認
- `reject_conflicts=True` が autopilot 確定経路すべてに残存。
- 対象者ゲート（グローバル＋患者個別）が無傷、条件が広がっていない。
- 非autopilot患者の旧分岐が残存。

---

## 7. 完了条件

- [ ] `_is_grounded_reply` による棄却→テンプレ差し替えが**廃止**され、LLMの返信がそのまま送られる。
- [ ] テンプレが出るのは API 障害時のみ。出たら `logger.error` ＋ 管理者通知で**可視化**される。
- [ ] `parsed_intent` の date/time/menu_hint が**実際に draft へ反映**される。
- [ ] **ボタンを一度も押さずに**「いつもので明日の14時」から予約確定まで到達できる。
- [ ] 「いつもので明日できますか？」に「メニューを選んでください」と返さない。
- [ ] autopilot 経路のハードコード返信（タスクC表の13箇所）が LLM 生成に置換された。
- [ ] 検証 A〜E すべて通過。
- [ ] 🔒原則1〜5 無傷（特に**対象者は合言葉登録者だけ**・対象外患者は無変更）。

---

## Copilotへの一言（コピペ用）

```
リポジトリ直下の INSTRUCTIONS_LINE_AUTOPILOT_LLM_ONLY_20260815.md を読んで実装して。
本書は指示書1〜3の返信生成に関する記述を上書きする（矛盾したら本書優先）。

目的はただ一つ:「LLMが読み、LLMが自然な返信文を書き、その文をそのまま送る」。
テンプレで返してよいのは外部API障害時のみで、その時はlogger.error＋管理者通知で可視化する。

現状の2大バグ:
(1) line_composer.py の _is_grounded_reply が、LLMの返信に事実の verbatim 復唱が無いと
    棄却してテンプレへ差し替えている → この棄却設計を全廃し、「矛盾時のみ1回作り直し」に変更。
(2) line.py:1265 でLLMが解析した parsed_intent の date/time/menu_hint がどこでも使われず、
    line.py:1873 の旧 waiting_menu 分岐（ボタン完全一致のみ）がテンプレを返している
    → autopilot患者は旧分岐をバイパスし、parsed_intent を draft に反映する統合スロット充填へ。

スコープ厳守: 自動化の対象は合言葉 #autopilot-setup で登録済みの患者のみ。
対象外患者・shadow経路・旧分岐は一切変更しない（本番は今もスタッフ手打ち運用中）。
reject_conflicts=True と対象者ゲートは死守。

検証A（テンプレが返信に出たら失敗するテスト）と検証B（実機ログ再現：ボタンを押さずに会話が進む）を
必ず追加して通すこと。
```
