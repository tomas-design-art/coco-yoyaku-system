# 接骨院予約管理システム

## 概要
接骨院の予約管理を紙ボードからデジタルに完全移行するためのWebアプリケーションです。

## 技術スタック
- **Frontend**: React + TypeScript + Vite + Tailwind CSS
- **Backend**: FastAPI + SQLAlchemy (async) + Alembic
- **Database**: PostgreSQL 15+
- **Container**: Docker + Docker Compose

## セットアップ

### 1. 環境変数
```bash
cp .env.example .env
# .envファイルを編集
```

### 2. Docker起動
```bash
docker-compose up --build
```

### 3. DBマイグレーション
```bash
docker-compose exec backend alembic upgrade head
```

### 4. 初期データ投入
```bash
docker-compose exec backend python scripts/seed.py
```

### 5. アクセス
- **フロントエンド**: http://localhost:5173
- **バックエンドAPI**: http://localhost:8000
- **API ドキュメント**: http://localhost:8000/docs

## 主な機能

### Phase 1（紙ボード完全置き換え）
- 5分刻みタイムテーブル（日表示/週表示）
- ドラッグ操作による予約登録
- 予約CRUD + 自動確定ロジック
- DB層でのEXCLUDE制約による二重予約完全防止
- ステータス遷移（確定/キャンセル申請/変更申請）
- SSEリアルタイム通知 + 通知音
- 施術者/メニュー/患者/設定管理

### Phase 2（外部チャネル連動）
- HotPepperメール自動解析→予約登録
- HotPepper枠押さえリマインド
- LINE予約メッセージ解析→予約提案

## テスト実行
```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```
