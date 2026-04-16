"""
1回限りのスクリプト: Render PostgreSQL に coco_staging データベースを作成する。

使い方:
  DATABASE_URL="postgresql://user:pass@host:5432/currentdb" python scripts/create_staging_db.py

  ※ DATABASE_URL は Render の External Database URL を指定してください。
"""

import os
import sys

from sqlalchemy import create_engine, text

TARGET_DB = "coco_staging"


def main() -> None:
    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        print("ERROR: DATABASE_URL 環境変数を設定してください。")
        sys.exit(1)

    # asyncpg URL が渡された場合は同期ドライバに変換
    url = raw_url.replace("postgresql+asyncpg://", "postgresql://")

    # AUTOCOMMIT でないと CREATE DATABASE は実行できない
    engine = create_engine(url, isolation_level="AUTOCOMMIT")

    with engine.connect() as conn:
        # 既に存在するかチェック
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": TARGET_DB},
        )
        if result.scalar():
            print(f"データベース '{TARGET_DB}' は既に存在します。スキップします。")
        else:
            # DB名はパラメータバインドできないため直接埋め込み（固定値なので安全）
            conn.execute(text(f'CREATE DATABASE "{TARGET_DB}"'))
            print(f"データベース '{TARGET_DB}' を作成しました。")

    engine.dispose()


if __name__ == "__main__":
    main()
