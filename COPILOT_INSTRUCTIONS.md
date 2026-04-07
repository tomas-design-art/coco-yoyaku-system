# COPILOT_INSTRUCTIONS.md — 実装指示書

**対象:** GitHub Copilot / Claude Code / Claude Opus
**目的:** SPEC_v3.md に基づき、接骨院予約管理システムを新規構築する
**優先度:** Phase 1 全機能 → Phase 2 全機能 を順番に実装

---

## 前提条件

- **ゼロから新規構築する。** 既存のStreamlit実装は使用しない
- **SPEC_v3.md が唯一の設計ドキュメント**。設計判断はすべてSPEC_v3.mdに従う
- 不明点がある場合は、勝手に判断せず確認を求めること
- 各Stepの完了時にテストを実行し、パスすることを確認してから次のStepに進む

---

## 技術スタック（厳守）

| レイヤー | 技術 | バージョン |
|---------|------|-----------|
| Frontend | React + TypeScript + Vite | React 18+, TS 5+ |
| CSS | Tailwind CSS | 3.x |
| Backend | FastAPI | 0.100+ |
| ORM | SQLAlchemy (async) | 2.0+ |
| Migration | Alembic | 1.12+ |
| DB | PostgreSQL | 15+ |
| Container | Docker + Docker Compose | — |
| AI（Phase 2） | Google Gemini API (gemini-2.5-flash) | — |

---

## 実装手順

以下のStepを**順番通り**に実装すること。各Stepには完了条件がある。

---

### Step 1: プロジェクト初期化

#### やること
1. SPEC_v3.md の「2.3 開発環境」に記載のディレクトリ構造を作成

2. **Python仮想環境を作成**（ローカル開発用）:
   ```bash
   cd backend
   python -m venv .venv

   # Windows (PowerShell)
   .\.venv\Scripts\Activate.ps1

   # Mac/Linux
   source .venv/bin/activate

   pip install -r requirements.txt
   ```
   > Docker内ではコンテナにPython環境が含まれるため .venv は不要。
   > ローカルでテスト実行や補完を効かせるために .venv を作っておく。
   > `.gitignore` に `.venv/` を必ず追加すること。

3. `docker-compose.yml` を作成:
   - `db`: PostgreSQL 15 (port 5432)
   - `backend`: FastAPI (port 8000)
   - `frontend`: Vite dev server (port 5173)
4. `.env.example` を作成:
   ```
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/reservation
   OPENAI_API_KEY=sk-xxx
   LINE_CHANNEL_SECRET=xxx
   LINE_CHANNEL_ACCESS_TOKEN=xxx
   SECRET_KEY=your-secret-key
   ```
4. `backend/requirements.txt`:
   ```
   fastapi>=0.100.0
   uvicorn[standard]>=0.23.0
   sqlalchemy[asyncio]>=2.0.0
   asyncpg>=0.28.0
   alembic>=1.12.0
   pydantic>=2.0.0
   pydantic-settings>=2.0.0
   python-dotenv>=1.0.0
   httpx>=0.25.0
   sse-starlette>=1.6.0
   apscheduler>=3.10.0
   ```
5. `frontend/package.json` に以下の依存関係:
   ```json
   {
     "dependencies": {
       "react": "^18.2.0",
       "react-dom": "^18.2.0",
       "react-router-dom": "^6.20.0",
       "axios": "^1.6.0",
       "date-fns": "^3.0.0",
       "lucide-react": "^0.300.0"
     },
     "devDependencies": {
       "@types/react": "^18.2.0",
       "@types/react-dom": "^18.2.0",
       "@vitejs/plugin-react": "^4.2.0",
       "autoprefixer": "^10.4.0",
       "postcss": "^8.4.0",
       "tailwindcss": "^3.4.0",
       "typescript": "^5.3.0",
       "vite": "^5.0.0"
     }
   }
   ```
6. Alembic初期化: `alembic init alembic`
7. `alembic/env.py` をasync対応に修正

#### 完了条件
- `docker-compose up` で3コンテナ（db, backend, frontend）がすべて起動する
- `http://localhost:8000/docs` でFastAPI Swagger UIが表示される
- `http://localhost:5173` でReact初期画面が表示される
- PostgreSQLに接続できる

---

### Step 2: バックエンド基盤 — DBモデル + マスタCRUD

#### やること

1. **SQLAlchemyモデルを定義** (`backend/app/models/`):

   **practitioners.py:**
   ```python
   class Practitioner(Base):
       __tablename__ = "practitioners"
       id = Column(Integer, primary_key=True, index=True)
       name = Column(String(100), nullable=False)
       role = Column(String(50), nullable=False, default="施術者")  # 院長/施術者
       is_active = Column(Boolean, default=True)
       display_order = Column(Integer, default=0)
       created_at = Column(DateTime(timezone=True), server_default=func.now())
       updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
   ```

   **patients.py:**
   ```python
   class Patient(Base):
       __tablename__ = "patients"
       id = Column(Integer, primary_key=True, index=True)
       name = Column(String(100), nullable=False)
       patient_number = Column(String(50), unique=True, nullable=True)  # 診察券番号
       phone = Column(String(20), nullable=True)
       email = Column(String(200), nullable=True)
       line_id = Column(String(100), nullable=True)
       notes = Column(Text, nullable=True)
       created_at = Column(DateTime(timezone=True), server_default=func.now())
       updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
   ```

   **menus.py:**
   ```python
   class Menu(Base):
       __tablename__ = "menus"
       id = Column(Integer, primary_key=True, index=True)
       name = Column(String(200), nullable=False)
       duration_minutes = Column(Integer, nullable=False)  # 施術時間（分）
       price = Column(Integer, nullable=True)  # 料金（円）
       is_active = Column(Boolean, default=True)
       display_order = Column(Integer, default=0)
       created_at = Column(DateTime(timezone=True), server_default=func.now())
       updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
   ```

   **reservations.py:**
   ```python
   # SPEC_v3.md セクション3.2 の全カラムを実装
   # EXCLUDE制約はAlembicマイグレーションで追加
   class Reservation(Base):
       __tablename__ = "reservations"
       id = Column(Integer, primary_key=True, index=True)
       patient_id = Column(Integer, ForeignKey("patients.id"), nullable=True)
       practitioner_id = Column(Integer, ForeignKey("practitioners.id"), nullable=False)
       menu_id = Column(Integer, ForeignKey("menus.id"), nullable=True)
       start_time = Column(DateTime(timezone=True), nullable=False)
       end_time = Column(DateTime(timezone=True), nullable=False)
       status = Column(String(20), nullable=False, default="PENDING")
       channel = Column(String(20), nullable=False)
       source_ref = Column(String(100), nullable=True)
       notes = Column(Text, nullable=True)
       conflict_note = Column(Text, nullable=True)
       hotpepper_synced = Column(Boolean, default=False)
       hold_expires_at = Column(DateTime(timezone=True), nullable=True)
       created_at = Column(DateTime(timezone=True), server_default=func.now())
       updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

       # Relationships
       patient = relationship("Patient", backref="reservations")
       practitioner = relationship("Practitioner", backref="reservations")
       menu = relationship("Menu", backref="reservations")
   ```

   **settings.py:**
   ```python
   class Setting(Base):
       __tablename__ = "settings"
       id = Column(Integer, primary_key=True, index=True)
       key = Column(String(100), unique=True, nullable=False)
       value = Column(String(500), nullable=False)
       updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
   ```

   **notification_log.py:**
   ```python
   class NotificationLog(Base):
       __tablename__ = "notification_log"
       id = Column(Integer, primary_key=True, index=True)
       reservation_id = Column(Integer, ForeignKey("reservations.id"), nullable=True)
       event_type = Column(String(50), nullable=False)
       message = Column(Text, nullable=False)
       is_read = Column(Boolean, default=False)
       created_at = Column(DateTime(timezone=True), server_default=func.now())
   ```

2. **Alembicマイグレーション作成:**
   ```bash
   alembic revision --autogenerate -m "initial tables"
   ```
   マイグレーションファイルに以下を**手動追加**:
   ```python
   # btree_gist拡張
   op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

   # EXCLUDE制約（二重予約防止の要）
   op.execute("""
       ALTER TABLE reservations ADD CONSTRAINT no_overlap
       EXCLUDE USING gist (
           practitioner_id WITH =,
           tstzrange(start_time, end_time) WITH &&
       )
       WHERE (status IN ('CONFIRMED', 'HOLD', 'PENDING'))
   """)
   ```

3. **初期データ投入スクリプト** (`backend/scripts/seed.py`):
   - settings テーブルに SPEC_v3.md セクション3.5 の初期値を挿入

4. **Pydanticスキーマ定義** (`backend/app/schemas/`):
   - 各モデルに対応する Create / Update / Response スキーマ
   - バリデーション付き（start_time < end_time、5分刻み等）

5. **マスタCRUD API** (`backend/app/api/`):
   - SPEC_v3.md セクション4.1 の施術者/患者/メニュー/設定APIをすべて実装
   - 患者検索: `GET /api/patients/search?q={query}` — 名前・診察券番号・電話番号で部分一致検索

#### 完了条件
- `alembic upgrade head` でテーブル作成成功
- EXCLUDE制約が有効 (`\d reservations` で確認)
- 各マスタCRUDが Swagger UI から操作可能
- 患者検索が動作する
- 初期設定データが投入されている

---

### Step 3: 予約コアロジック

#### やること

1. **予約サービス** (`backend/app/services/reservation_service.py`):
   - SPEC_v3.md セクション6.1「自動確定ルール」を実装
   - SPEC_v3.md セクション6.5「競合検出」を実装
   - 予約登録時: 自動確定判定 → DB INSERT → EXCLUDE制約チェック → 409 or 201

2. **ステータス遷移API**:
   - `POST /api/reservations/{id}/confirm` — PENDING → CONFIRMED
   - `POST /api/reservations/{id}/cancel-request` — CONFIRMED → CANCEL_REQUESTED
   - `POST /api/reservations/{id}/cancel-approve` — CANCEL_REQUESTED → CANCELLED
   - `POST /api/reservations/{id}/change-request` — body に新時間帯。旧予約→CHANGE_REQUESTED、新時間帯→HOLD
   - `POST /api/reservations/{id}/change-approve` — 旧CANCELLED、新CONFIRMED
   - **不正な遷移は400エラーで拒否**（例: CANCELLED → CONFIRMED）

3. **HOLD自動失効ジョブ**:
   - APSchedulerで1分間隔
   - `hold_expires_at < NOW()` かつ `status = 'HOLD'` → `status = 'EXPIRED'`

4. **バリデーション**:
   - start_time, end_time が5分刻みであること
   - start_time < end_time
   - 営業時間内（settings から取得）
   - practitioner_id が有効（is_active=True）

#### 完了条件
- 予約登録が成功する（CONFIRMED / PENDING が正しく判定される）
- 同一施術者の同時間帯に2件登録しようとすると409エラー
- ステータス遷移が正しく動作する
- 不正遷移が拒否される
- HOLD予約が10分後に自動でEXPIREDになる

**テスト必須:**
```python
# tests/test_reservations.py
def test_create_reservation_confirmed():
    """全条件満たす → CONFIRMED"""

def test_create_reservation_pending():
    """menu_id未指定 → PENDING"""

def test_conflict_detection():
    """同一施術者の重複予約 → 409"""

def test_cancel_flow():
    """CONFIRMED → CANCEL_REQUESTED → CANCELLED"""

def test_change_flow():
    """CONFIRMED → CHANGE_REQUESTED + HOLD → 旧CANCELLED + 新CONFIRMED"""

def test_hold_expiration():
    """HOLD → 期限後にEXPIRED"""

def test_invalid_transition():
    """CANCELLED → CONFIRMED は400エラー"""
```

---

### Step 4: フロントエンド基盤

#### やること

1. Vite + React + TypeScript + Tailwind CSS セットアップ
2. React Router でページルーティング:
   - `/` — タイムテーブル
   - `/patients` — 患者管理
   - `/settings/practitioners` — 施術者管理
   - `/settings/menus` — メニュー管理
   - `/settings` — システム設定
   - `/hotpepper` — Phase 2: HotPepper同期
3. APIクライアント (`src/api/client.ts`): axios でバックエンドと通信
4. TypeScript型定義 (`src/types/index.ts`): SPEC_v3.md のレスポンス型に対応
5. 共通レイアウト: ヘッダー（ナビ + 通知ベル）+ メインコンテンツ

#### 完了条件
- 各ページにルーティングで遷移できる
- APIクライアントからバックエンドにリクエストが通る
- Tailwind CSSが適用されている

---

### Step 5: タイムテーブルUI

**最重要画面。SPEC_v3.md セクション5.2 を忠実に実装する。**

#### やること

1. **TimeTable.tsx** — メインコンポーネント:
   - 5分刻みのグリッド（09:00〜20:00 = 132行）
   - 施術者ごとの列（is_active=True の施術者を display_order 順で表示）
   - 予約データを GET /api/reservations?start_date=...&end_date=... で取得
   - 予約ブロックを正しい位置に配置

2. **ReservationBlock.tsx** — 予約ブロック:
   - SPEC_v3.md セクション5.2 の色分け
   - チャネルアイコン表示
   - 患者名 + メニュー名を表示
   - クリックで詳細ポップオーバー

3. **DragSelect.tsx** — ドラッグ選択:
   - 空きスロットでマウスダウン→ドラッグ→マウスアップで時間範囲選択
   - 選択範囲をハイライト表示
   - マウスアップ時に予約登録モーダルを開く（start_time, end_time をプリセット）

4. **日表示 / 週表示の切替**:
   - 日表示: 全施術者を横並び（デフォルト）
   - 週表示: 1施術者の月〜日を横並び

5. **ナビゲーション**:
   - ←→ボタンで週/日を切替
   - 「今日」ボタンで当日にジャンプ

#### UI実装のポイント
```
- グリッドは CSS Grid で実装
- 行の高さ: 各5分スロット = 20px（調整可能）
- 時間ラベルは15分ごと（09:00, 09:15, 09:30...）に表示、5分行は罫線のみ
- 予約ブロックは position: absolute で配置（top = スロット位置、height = 時間幅）
- ドラッグ中はカーソルを col-resize に変更
```

#### 完了条件
- 5分刻みのグリッドが正しく表示される
- 予約ブロックが正しい位置・高さで表示される
- 色分けが正しい
- ドラッグで時間範囲を選択できる
- 日表示/週表示が切り替わる
- 週ナビゲーションが動作する

---

### Step 6: 予約操作UI

#### やること

1. **ReservationForm.tsx** — 予約登録/編集モーダル:
   - SPEC_v3.md セクション5.3 のレイアウト
   - 患者検索（PatientSearch.tsx）: 2文字以上でインクリメンタルサーチ
   - 新規患者インライン登録
   - メニュー選択時に duration_minutes から end_time を自動計算
   - 手動で end_time 変更可能（5分刻み select）
   - channel 選択
   - 登録時に POST /api/reservations

2. **予約詳細ポップオーバー**:
   - 予約ブロッククリックで表示
   - 患者情報・メニュー・時間・ステータス表示
   - アクションボタン:
     - PENDING: [確定する] [却下する]
     - CONFIRMED: [変更申請] [キャンセル申請]
     - CANCEL_REQUESTED: [キャンセル承認]
     - CHANGE_REQUESTED: [変更承認]

3. **競合エラーハンドリング**:
   - 409 Conflict 時に競合予約の情報を表示
   - 「この時間帯は ○○様（10:00-10:45）と重複しています」

#### 完了条件
- タイムテーブルからクリック/ドラッグで予約登録モーダルが開く
- 患者検索が動作する
- メニュー選択で終了時間が自動計算される
- 予約登録が成功する
- 競合時に409エラーとわかりやすいメッセージが表示される
- ステータス遷移（確定・キャンセル申請・承認等）がUIから操作できる

---

### Step 7: 通知システム

#### やること

1. **バックエンド SSE** (`backend/app/api/sse.py`):
   - `GET /api/sse/events` — SSEストリーム
   - 予約登録/変更/キャンセル時にイベントを発火
   - イベント種別: SPEC_v3.md セクション5.4

2. **フロントエンド SSE** (`src/hooks/useSSE.ts`):
   - EventSource で接続
   - イベント受信時にタイムテーブルをリフレッシュ

3. **通知音** (`src/utils/soundUtils.ts`):
   - Web Audio API で通知音を再生
   - 営業時間内のみ再生（settingsから取得）
   - 初回クリック時に AudioContext を初期化（ブラウザ制約対応）

4. **通知ベル + ポップアップ** (`src/components/Notification/`):
   - ヘッダーの通知ベルに未読数バッジ
   - 新規イベント時にトースト通知表示（3秒で自動消去）
   - 競合検出時は赤トースト + 消えない（手動で閉じる）

5. **notification_log**:
   - イベント発生時にDBに記録
   - GET /api/notifications で一覧取得
   - PUT /api/notifications/{id}/read で既読

#### 完了条件
- 別タブで予約を登録すると、メインタブにリアルタイムで反映される
- 通知音が鳴る
- トースト通知が表示される
- 通知ベルの未読数が更新される

---

### Step 8: 管理画面

#### やること

1. **施術者管理** (`/settings/practitioners`):
   - 一覧表示（display_order順）
   - 追加/編集/無効化（論理削除）
   - display_orderの並び替え

2. **メニュー管理** (`/settings/menus`):
   - 一覧表示
   - 追加/編集/無効化
   - duration_minutes, price の設定

3. **システム設定** (`/settings`):
   - SPEC_v3.md セクション3.5 の全設定を編集可能
   - HOLD時間、営業時間、通知音ON/OFF等

4. **シンプル認証**:
   - 環境変数で管理者パスワードを設定
   - ログイン画面 → 認証成功でセッション発行
   - 全ページで認証チェック

#### 完了条件
- 施術者/メニューの追加・編集・無効化ができる
- 施術者を追加するとタイムテーブルに列が増える
- 設定変更が即座に反映される
- 未認証時はログイン画面にリダイレクトされる

---

### Step 9: テスト

#### やること

1. **バックエンドテスト** (`backend/tests/`):
   - 予約CRUD
   - 競合検出（EXCLUDE制約）
   - ステータス遷移（正常系 + 異常系）
   - HOLD自動失効
   - 自動確定ルール

2. **フロントエンドテスト**:
   - タイムテーブル表示
   - 予約登録フロー
   - ドラッグ選択

#### 完了条件
- 全テストがパスする
- Phase 1 の全機能が動作する

---

### Step 10: HotPepperメール解析（Phase 2）

#### やること

1. **メール取得アダプター** (`backend/app/services/hotpepper_mail.py`):
   - `MailFetcher` 抽象クラス
   - `GmailFetcher` — Gmail API (OAuth2)
   - `IMAPFetcher` — 汎用IMAP
   - 環境変数で切替: `MAIL_PROVIDER=gmail` or `MAIL_PROVIDER=imap`

2. **AIメール解析** (`backend/app/agents/mail_parser.py`):
   - SPEC_v3.md セクション7.1 のプロンプト使用
   - メール本文 → JSON（顧客名、日時、メニュー、予約番号）
   - パース失敗時はエラーログ + 管理画面通知

3. **ポーリングジョブ**:
   - APSchedulerで5分間隔（設定変更可能）
   - 新規HotPepperメールを検出 → 解析 → 予約登録
   - source_ref にHotPepper予約番号を記録（重複登録防止）

4. **予約登録（HotPepper固有ロジック）**:
   - channel = "HOTPEPPER"
   - **競合があっても登録する**（外部で確定済みのため）
   - 競合時: conflict_note に情報を記録 + 強アラート通知

5. **API**:
   - `POST /api/hotpepper/parse-email` — 手動解析（テスト用）
   - `POST /api/hotpepper/trigger-poll` — 手動ポーリング実行

#### 完了条件
- テスト用メール本文を POST すると予約データが正しく抽出される
- 抽出データから予約が自動登録される
- 競合時にアラートが表示される
- 同じ予約番号の二重登録が防止される

---

### Step 11: HotPepper枠押さえリマインド（Phase 2）

#### やること

1. **予約登録フック**:
   - channel != "HOTPEPPER" の予約が登録された際:
     - 通知:「HotPepper側の {date} {time} を押さえてください」
     - hotpepper_synced = false

2. **未押さえ一覧画面** (`/hotpepper`):
   - `GET /api/hotpepper/pending-sync` — hotpepper_synced=false の予約一覧
   - 「押さえ済み」ボタン → `POST /api/hotpepper/{id}/mark-synced`

3. **リマインド通知**:
   - 未押さえ予約がある場合、30分間隔でリマインド通知

#### 完了条件
- 電話/窓口/LINE予約登録時にHP押さえリマインドが表示される
- 未押さえ一覧が確認できる
- 押さえ済みマークで一覧から消える

---

### Step 12: LINE連携（Phase 2）

#### やること

1. **LINE Webhook受信** (`backend/app/api/line.py`):
   - 署名検証
   - メッセージイベントの処理

2. **AIメッセージ解析** (`backend/app/agents/line_parser.py`):
   - ユーザーメッセージから予約意図を判定
   - 予約意図あり: 日時・メニュー等を抽出 → 予約提案
   - 予約意図なし: 通常メッセージとして通知

3. **予約提案フロー**:
   - 管理画面に提案を表示:「LINE: ○○様が 3/15 10:00 を希望」
   - [承認] → 予約登録 + LINE返信「予約を確定しました」
   - [別日提案] → テキスト入力 → LINE返信
   - [却下] → LINE返信「申し訳ございません...」

4. **LINE返信** (`backend/app/services/line_reply.py`):
   - LINE Messaging API で返信

#### 完了条件
- LINEからのメッセージが管理画面に表示される
- 予約意図のあるメッセージが予約提案として表示される
- 承認すると予約が登録される
- LINEに確認メッセージが返信される

---

### Step 13: 統合テスト（Phase 2）

#### やること
- HotPepperメール→予約登録→競合検出→通知 のE2Eテスト
- LINE→予約提案→承認→登録 のE2Eテスト
- 複数チャネルからの同時予約→競合検出テスト

#### 完了条件
- 全E2Eテストがパスする
- Phase 1 + Phase 2 の全機能が動作する

---

## コーディング規約

### バックエンド（Python）
- 型ヒント必須
- async/await パターンで統一
- docstring は日本語OK
- エラーハンドリング: HTTPException を適切に使用
- ログ: logging モジュールを使用

### フロントエンド（TypeScript）
- 関数コンポーネント + Hooks
- 型定義は `src/types/` に集約
- API呼び出しは `src/api/client.ts` に集約
- CSS は Tailwind のユーティリティクラスを使用
- コンポーネントは小さく分割

### 共通
- コミットメッセージ: `feat:`, `fix:`, `refactor:`, `test:`, `docs:` プレフィックス
- 各Stepの完了時にコミット

---

## トラブルナレッジの記録と参照（MEMORY.md 運用ルール）

### 概要

開発中に発生したトラブル・ハマりポイント・解決策を `MEMORY.md` に記録し、以降の開発で同じミスを繰り返さないようにする。
**AIエージェント（Copilot / Claude Code）は、各Stepの作業開始前に必ず MEMORY.md を読み、過去のトラブルに該当する作業がないか確認すること。**

### ファイル配置

```
repo/
├── MEMORY.md          ← ここに記録
├── SPEC_v3.md
├── COPILOT_INSTRUCTIONS.md
└── ...
```

### MEMORY.md のフォーマット

```markdown
# 開発トラブルナレッジ

## [YYYY-MM-DD] タイトル（短く問題を要約）

- **Step:** Step X（該当するStep番号）
- **カテゴリ:** 環境構築 / DB / API / フロントエンド / テスト / デプロイ / その他
- **問題:** 何が起きたか（エラーメッセージ含む）
- **原因:** なぜ起きたか
- **解決策:** どう直したか
- **教訓:** 次回から何に気をつけるか

---
```

### 記録ルール

1. **トラブル発生時は即記録する。** 解決後に書くのではなく、発生→原因調査→解決の過程をリアルタイムで記録する
2. **エラーメッセージは省略せずそのまま貼る**（後から検索できるように）
3. **「なぜ」を必ず書く。** 「Xを実行したら動いた」だけでは不十分。なぜそれで動いたのかを記録する
4. **些細なことでも記録する。** 「pip install で --break-system-packages が必要だった」レベルのことでもOK

### 参照ルール（AIエージェント向け — 最重要）

1. **各Stepの作業開始前に MEMORY.md を読む。** これは必須。スキップしてはいけない
2. 現在のStepに関連するトラブルがあれば、その教訓を踏まえて作業する
3. 過去と同じエラーが出た場合、MEMORY.md の解決策を最初に試す
4. 新しいトラブルが発生したら、作業を中断してまず MEMORY.md に記録してから解決に取り組む

### 記録の例

```markdown
## [2026-03-10] Alembic EXCLUDE制約がautogenerateで検出されない

- **Step:** Step 2
- **カテゴリ:** DB
- **問題:** `alembic revision --autogenerate` でEXCLUDE制約が生成されない
- **原因:** AlembicのautogenerateはEXCLUDE制約を検出できない（PostgreSQL固有機能のため）
- **解決策:** マイグレーションファイルに `op.execute()` で手動追加する
- **教訓:** PostgreSQL固有の制約（EXCLUDE, GiST等）はautogenerateに頼らず、必ず手動でマイグレーションに追加する

---

## [2026-03-10] ブラウザで通知音が鳴らない

- **Step:** Step 7
- **カテゴリ:** フロントエンド
- **問題:** 通知音が再生されない。コンソールに "The AudioContext was not allowed to start" エラー
- **原因:** ブラウザのAutoplay Policy。ユーザー操作なしにAudio再生は不可
- **解決策:** 初回のクリックイベントで `audioContext.resume()` を呼ぶ
- **教訓:** Web Audio APIは必ずユーザージェスチャー後に初期化する。アプリ起動時に「通知を有効にする」ボタンを用意する

---
```
