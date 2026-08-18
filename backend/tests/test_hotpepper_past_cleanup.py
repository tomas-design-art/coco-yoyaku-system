"""HotPepper未同期一覧の日付境界と、過去分一括同期（ドライラン/実行）の検証。"""
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.hotpepper import (
    BulkMarkPastSyncedRequest,
    _past_unsynced_summary,
    _today_start_jst,
    mark_past_unsynced,
    past_unsynced_filters,
    pending_sync_filters,
)
from app.database import Base
from app.models.audit_log import AuditLog
from app.models.menu import Menu
from app.models.patient import Patient
from app.models.practitioner import Practitioner
from app.models.reservation import Reservation
from app.models.reservation_color import ReservationColor
from app.models.reservation_series import ReservationSeries
from app.utils.datetime_jst import now_jst


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Patient.__table__,
                Practitioner.__table__,
                Menu.__table__,
                ReservationColor.__table__,
                ReservationSeries.__table__,
                Reservation.__table__,
                AuditLog.__table__,
            ],
        )
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _seed(db: AsyncSession) -> dict[str, int]:
    now = now_jst()
    rows = {
        "past": now - timedelta(days=120),
        "yesterday": now - timedelta(days=1),
        "today_later": now + timedelta(hours=2),
        "future": now + timedelta(days=30),
        "beyond_horizon": now + timedelta(days=120),
    }
    ids: dict[str, int] = {}
    for label, start in rows.items():
        reservation = Reservation(
            practitioner_id=1,
            start_time=start,
            end_time=start + timedelta(minutes=45),
            status="CONFIRMED",
            channel="LINE",
            hotpepper_synced=False,
        )
        db.add(reservation)
        await db.flush()
        ids[label] = reservation.id
    await db.commit()
    return ids


@pytest.mark.asyncio
async def test_pending_sync_excludes_past_and_beyond_horizon(session):
    ids = await _seed(session)

    visible = (
        await session.execute(
            select(Reservation.id).where(*pending_sync_filters(now_jst(), 90))
        )
    ).scalars().all()

    assert set(visible) == {ids["today_later"], ids["future"]}
    assert ids["past"] not in visible
    assert ids["yesterday"] not in visible
    assert ids["beyond_horizon"] not in visible


@pytest.mark.asyncio
async def test_past_unsynced_preview_never_includes_future(session):
    ids = await _seed(session)

    summary = await _past_unsynced_summary(session, _today_start_jst())

    assert summary["count"] == 2
    assert set(summary["ids"]) == {ids["past"], ids["yesterday"]}
    assert ids["today_later"] not in summary["ids"]
    assert ids["future"] not in summary["ids"]
    assert ids["beyond_horizon"] not in summary["ids"]
    assert sum(item["count"] for item in summary["by_month"]) == 2


@pytest.mark.asyncio
async def test_bulk_mark_past_synced_requires_confirmation(session):
    from fastapi import HTTPException

    await _seed(session)

    with pytest.raises(HTTPException) as error:
        await mark_past_unsynced(
            BulkMarkPastSyncedRequest(confirm=False),
            db=session,
            x_operator="tester",
            _auth={"role": "admin"},
        )

    assert error.value.status_code == 400
    remaining = (
        await session.execute(select(Reservation.id).where(*past_unsynced_filters(_today_start_jst())))
    ).scalars().all()
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_bulk_mark_past_synced_updates_only_past_and_writes_audit_log(session):
    ids = await _seed(session)

    result = await mark_past_unsynced(
        BulkMarkPastSyncedRequest(confirm=True),
        db=session,
        x_operator="%E7%AE%A1%E7%90%86%E8%80%85",
        _auth={"role": "admin"},
    )

    assert result["updated"] == 2

    synced = {
        row[0]: row[1]
        for row in (await session.execute(select(Reservation.id, Reservation.hotpepper_synced))).all()
    }
    assert synced[ids["past"]] is True
    assert synced[ids["yesterday"]] is True
    assert synced[ids["today_later"]] is False
    assert synced[ids["future"]] is False
    assert synced[ids["beyond_horizon"]] is False

    logs = (await session.execute(select(AuditLog))).scalars().all()
    assert [log.action for log in logs] == ["HOTPEPPER_BULK_MARK_PAST_SYNCED"]
    assert logs[0].operator == "管理者"
    assert logs[0].detail["count"] == 2
