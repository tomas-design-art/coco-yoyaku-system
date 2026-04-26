"""本番タイムテーブルをstaging DBへ片方向同期する検証用スクリプト。

安全仕様:
- 自動実行しない。手動/ジョブ実行専用。
- PRODUCTION_SYNC_ENABLED=true と SYNC_PRODUCTION_TO_STAGING_CONFIRM=YES が必須。
- source と target が同一URLなら中止。
- target URL に staging/coco_staging が含まれない場合は原則中止。

想定:
  PRODUCTION_DATABASE_URL="postgresql+asyncpg://...prod..." \
  STAGING_DATABASE_URL="postgresql+asyncpg://...staging..." \
  PRODUCTION_SYNC_ENABLED=true \
  SYNC_PRODUCTION_TO_STAGING_CONFIRM=YES \
  python scripts/sync_production_to_staging.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base  # noqa: E402
from app.services.bootstrap import _import_all_models  # noqa: E402


TABLES_IN_INSERT_ORDER = [
    "settings",
    "reservation_colors",
    "practitioners",
    "patients",
    "menus",
    "menu_price_tiers",
    "weekly_schedules",
    "practitioner_schedules",
    "date_overrides",
    "practitioner_unavailable_times",
    "reservation_series",
    "reservations",
]


def _normalize_asyncpg_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def _safe_url_label(url: str) -> str:
    if "@" not in url:
        return url
    prefix, suffix = url.split("@", 1)
    scheme = prefix.split("://", 1)[0]
    return f"{scheme}://***@{suffix}"


def _require_enabled(source_url: str, target_url: str) -> None:
    if os.environ.get("PRODUCTION_SYNC_ENABLED", "").lower() != "true":
        raise SystemExit("ERROR: PRODUCTION_SYNC_ENABLED=true が必要です。")
    if os.environ.get("SYNC_PRODUCTION_TO_STAGING_CONFIRM") != "YES":
        raise SystemExit("ERROR: SYNC_PRODUCTION_TO_STAGING_CONFIRM=YES が必要です。")
    if not source_url or not target_url:
        raise SystemExit("ERROR: PRODUCTION_DATABASE_URL と STAGING_DATABASE_URL/DATABASE_URL が必要です。")
    if source_url == target_url:
        raise SystemExit("ERROR: source と target が同一です。中止します。")
    target_lower = target_url.lower()
    if "staging" not in target_lower and "coco_staging" not in target_lower:
        if os.environ.get("ALLOW_NON_STAGING_TARGET") != "YES":
            raise SystemExit("ERROR: target が staging に見えません。ALLOW_NON_STAGING_TARGET=YES なしでは実行しません。")


async def _read_table_rows(conn, table_name: str) -> list[dict]:
    table = Base.metadata.tables[table_name]
    result = await conn.execute(select(table))
    return [dict(row._mapping) for row in result.fetchall()]


async def _delete_target_tables(conn, table_names: Iterable[str]) -> None:
    for table_name in reversed(list(table_names)):
        table = Base.metadata.tables[table_name]
        await conn.execute(delete(table))


async def _insert_rows(conn, table_name: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    table = Base.metadata.tables[table_name]
    await conn.execute(table.insert(), rows)
    return len(rows)


async def main() -> None:
    _import_all_models()

    source_url = _normalize_asyncpg_url(os.environ.get("PRODUCTION_DATABASE_URL", ""))
    target_url = _normalize_asyncpg_url(os.environ.get("STAGING_DATABASE_URL") or os.environ.get("DATABASE_URL", ""))
    _require_enabled(source_url, target_url)

    missing_tables = [t for t in TABLES_IN_INSERT_ORDER if t not in Base.metadata.tables]
    if missing_tables:
        raise SystemExit(f"ERROR: 同期対象テーブルが見つかりません: {', '.join(missing_tables)}")

    print("=== production -> staging sync ===")
    print(f"source: {_safe_url_label(source_url)}")
    print(f"target: {_safe_url_label(target_url)}")

    source_engine = create_async_engine(source_url, echo=False)
    target_engine = create_async_engine(target_url, echo=False)

    try:
        table_rows: dict[str, list[dict]] = {}
        async with source_engine.connect() as source_conn:
            for table_name in TABLES_IN_INSERT_ORDER:
                rows = await _read_table_rows(source_conn, table_name)
                table_rows[table_name] = rows
                print(f"read  {table_name}: {len(rows)} rows")

        async with target_engine.begin() as target_conn:
            await _delete_target_tables(target_conn, TABLES_IN_INSERT_ORDER)
            for table_name in TABLES_IN_INSERT_ORDER:
                count = await _insert_rows(target_conn, table_name, table_rows[table_name])
                print(f"write {table_name}: {count} rows")
    finally:
        await source_engine.dispose()
        await target_engine.dispose()

    print("sync complete")


if __name__ == "__main__":
    asyncio.run(main())
