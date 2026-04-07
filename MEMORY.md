# 開発トラブルナレッジ

## 実装済みフェーズ (2026-03-21)

### PATCH_001 完了
- `reservation_colors` テーブル追加（migration 002）
- `reservations.color_id` FK追加
- `channel` ENUM: WEB削除 → CHATBOT追加
- フロントエンド: ColorManager、ReservationFormカラーピッカー、TimeTable/ReservationBlock色優先ロジック

### PATCH_002 完了（Step 14〜16）
- Step 14: `chatbot_agent.py`（Tool定義）+ `chatbot_service.py`（LLM呼び出し/Gemini API/レート制限）+ `chatbot.py`（API）
- Step 15: `ChatWidget.tsx`+Shadow DOM埋め込み（`widget-entry.tsx`）+ `vite.widget.config.ts`
- Step 16: `ChatbotSettings.tsx`（ON/OFF・受付時間・メッセージ編集）

## 注意事項・ポイント

### `types/index.ts` 末尾に重複CHANNEL_ICONSが残存していた
- 旧WEB版の古いブロックが末尾に残っており、TypeScriptエラーは出ないが定義が重複
- 修正済み: 末尾の旧ブロック（WEB: '🌐'）を削除

### `main.py` で chatbot モジュールを先にimport宣言していた
- `chatbot.py` を作る前に `main.py` が import していたため、実装中はサーバー起動不可
- 対策: chatbot.py 作成を最優先にすること（今回は同日中に作成し解消）

### LLM APIキー未設定時のフォールバック
- `GEMINI_API_KEY` 未設定の場合、固定メッセージを返す
- 本番前に `.env` に Gemini API キーを設定必要

### `chatbot_enabled` 設定はseed.py + DBに存在する必要がある

## PATCH_005 (2026-03-26)

### 二段階認証
- `passlib[bcrypt]` + `bcrypt==4.0.1` ピン止め必須（bcrypt 4.2+で`__about__`属性ValueError）
- ログアウト→PIN画面の遷移: `navigate('/')` をlogoutハンドラに置くと `AuthGate` がAppContentをunmountしてnavigateが効かない → `justLoggedOut` フラグ + LoggedOutScreen で2秒ワンクッション方式に変更

### 職員勤務スケジュール管理 (migration 006)
- テーブル: `practitioner_schedules` (曜日別デフォルト), `schedule_overrides` (臨時休み/出勤)
- 判定ロジック: override優先 → default → レコードなし=出勤扱い
- TimeTable: `PractitionerDayStatus` APIをfetchし、休みの施術者セルをグレー斜線パターンでオーバーレイ
- `activePractitioners` をuseEffect依存に入れると無限ループリスクあり → `activePractitionerIds` (string join) で安定化
- `scripts/seed.py` にデフォルト値追加済み
- 初回起動時に `python scripts/seed.py` を実行すること

## 実装済みフェーズ (2026-03-22)

### JST 対応 + デモデータ (PATCH_003)
**バックエンド**
- `backend/app/utils/datetime_jst.py` 追加: `now_jst()` / `JST = ZoneInfo("Asia/Tokyo")`
- `hold_expiration.py`: `datetime.now(timezone.utc)` → `now_jst()` に置き換え
- `reservation_service.py`: `hold_expires_at` 計算で `now_jst()` 使用
- `schemas/reservation.py`: `ReservationResponse` に `@field_serializer` 追加 → すべての datetime を `+09:00` オフセット付き ISO 文字列で返す

**フロントエンド**
- `timeUtils.ts` の `dateToMinutes()` を JST 算術で修正 (UTC+9h のオフセット計算)
- `getTodayJST()` / `getNowJSTMinutes()` を `timeUtils.ts` に追加
- `TimeTable.tsx`:
  - 初期 `currentDate` → `getTodayJST()` で JST 当日に
  - 「今日」ボタン → `getTodayJST()` を使用
  - 現在時刻インジケーター (赤横線+丸): `nowMinutes` state + 1分 setInterval
  - 今日カラムのみインジケーター表示 (日・週両対応)

**デモデータ**
- `backend/scripts/seed_demo.py` 追加
- 施術者3名・メニュー6種・予約色3色・患者10名・今週の予約28件
- ステータスカバレッジ: CONFIRMED/PENDING/HOLD/CANCEL_REQUESTED/CHANGE_REQUESTED
- conflict_note付き・hotpepper_synced=false/true 含む
- 冪等: source_ref='DEMO-XXX' が存在すれば SKIP

**注意事項**
- Alembic 002 (reservation_colors / color_id / chat_sessions) は 001 適用後に手動 `alembic upgrade head` が必要
- 初回起動手順: `alembic upgrade head` → `python scripts/seed.py` → `python scripts/seed_demo.py`
- `day` importを消しすぎると `datetime` NameError になる: `reservation_service.py` は `from datetime import datetime, timedelta` が必要
- `chatbot_service.py`, `auth.py`, `line_parser.py` にも `datetime.now()` / `utcnow()` が残存していた → `now_jst()` に統一済み (2026-03-22 追加修正)

### Viteプロキシ + FastAPI trailing slash リダイレクト問題 (2026-03-22)
- **現象**: UIで施術者・患者・メニューなど全データが表示されない（画面空っぽ）
- **原因**: `client.ts` が `/api/practitioners` (末尾スラッシュなし) でリクエスト → FastAPI が `Location: http://backend:8000/api/practitioners/` にリダイレクト → ブラウザが Docker 内部ホスト名 `backend:8000` を解決できず失敗
- **修正**: `client.ts` の全リスト取得・POST URL に末尾スラッシュ `/` を追加
- **教訓**: FastAPI のルート定義が `@router.get("/")` の場合、クライアント側の URL にも必ず末尾スラッシュを付けること。Vite proxy の `changeOrigin: true` は Location ヘッダーを書き換えない

（以降トラブル発生次第追記する）

## 実行記録 (2026-03-31 まで)

### 施術者の時間帯休みフォーム改善
- 時間帯休みの開始/終了デフォルトを固定値ではなく、院の営業時間設定に追従するよう変更
- 入力UIにも営業時間の min/max を適用し、範囲外入力を抑制

### 患者デフォルト設定追加
- patients に `default_menu_id` と `default_duration` を追加
- APIスキーマ（作成/更新/応答）に同項目を反映
- マイグレーション `012_patient_defaults.py` を追加・適用

### 繰り返し予約（一括生成ツール）
- 仕様はシリーズ管理ではなく「一括生成」に限定（親子構造・一括変更は未導入）
- バックエンドに `POST /api/reservations/bulk` を追加
- 頻度（毎週/隔週/毎月）と終了条件（終了日 or 回数）で日付生成
- 個別生成時に競合/休診/不在などの失敗はスキップし、作成件数・スキップ理由を返却

### フロントエンド反映
- 予約フォームに繰り返し予約UI（頻度・終了条件）を追加
- 一括生成結果（成功件数/スキップ詳細）を表示
- 患者選択時に `default_menu_id` / `default_duration` を予約フォームへ自動反映
- 患者編集画面にデフォルトメニュー/デフォルト時間の設定項目を追加

### 検証結果
- backend: テスト 201 passed（既知の日時依存テスト 1 件は deselect）
- 既知の別件: 既存コード由来の TypeScript 未使用変数/既存型不一致が一部残存（今回変更箇所はエラーなし）

### MissingGreenlet 根本原因と統一修正 (2026-03-22)
- **現象**: 予約のステータス遷移（キャンセル申請、確定、却下等）や予約作成時に 500 エラー
- **根本原因**: `db.commit()` 後に `db.refresh(obj, ["patient", "practitioner", ...])` を使用。これはリレーション属性のみ再ロードし、**スカラー属性 (updated_at, status 等) は expired のまま**。その後 `build_reservation_response()` でスカラー属性にアクセスすると同期 lazy load が走り、async セッションでは `MissingGreenlet` が発生
- **修正パターン**: `db.commit()` 後は必ず `selectinload` 付きの `select()` で全属性を再取得する:
  ```python
  await db.commit()
  result = await db.execute(
      select(Reservation).where(Reservation.id == rid)
      .options(selectinload(...), selectinload(...), ...)
  )
  reservation = result.scalar_one()
  ```
- **修正箇所**: `reservations.py` の全ステータス遷移EP + `update_reservation`、`reservation_service.py` の `create_reservation` + `handle_change_request`
- **追加修正**: `conflict_detector.py` の競合検出クエリに `selectinload(Reservation.patient)` を追加（conflict_note 生成時に `c.patient.name` にアクセスするため）
- **教訓**: async SQLAlchemy では `db.refresh(obj, [relation_names])` は危険。`commit()` 後は常に `selectinload` 付き再クエリを使うこと。`db.refresh(obj)` （引数なし）は全スカラーを再ロードするので安全だが、リレーションは含まない
