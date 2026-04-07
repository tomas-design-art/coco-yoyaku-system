"""Phase 2/3 回帰テスト: HOLD期限切れ通知、HotPepper冪等、チャット確定、振替候補"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


class _FakeScalarResult:
    def __init__(self, items: list):
        self._items = items

    def all(self):
        return self._items


class _FakeResult:
    def __init__(self, all_items: list | None = None, one: object | None = None):
        self._all_items = all_items or []
        self._one = one

    def scalars(self):
        return _FakeScalarResult(self._all_items)

    def scalar_one_or_none(self):
        return self._one


@dataclass
class _AsyncSessionCtx:
    db: AsyncMock

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_expire_holds_creates_hold_expired_notifications():
    from app.services.hold_expiration import expire_holds

    now = datetime(2026, 4, 3, 10, 0, 0)
    expired_reservation = SimpleNamespace(
        id=42,
        status="HOLD",
        hold_expires_at=now - timedelta(minutes=1),
    )

    db = AsyncMock()
    db.execute.return_value = _FakeResult(all_items=[expired_reservation])

    with patch("app.services.hold_expiration.async_session", return_value=_AsyncSessionCtx(db)), patch(
        "app.services.hold_expiration.create_notification", new_callable=AsyncMock
    ) as mock_notify, patch("app.services.hold_expiration.now_jst", return_value=now):
        await expire_holds()

    assert expired_reservation.status == "EXPIRED"
    mock_notify.assert_awaited_once_with(
        db,
        "hold_expired",
        "HOLD期限切れ: 予約#42",
        42,
    )
    db.commit.assert_awaited_once()


def test_hotpepper_sync_reminder_uses_canonical_event_name_in_scheduler_service():
    service_file = Path(__file__).resolve().parents[1] / "app" / "services" / "hold_expiration.py"
    text = service_file.read_text(encoding="utf-8")

    assert '"hotpepper_sync_reminder"' in text
    assert '"hotpepper_hold_reminder"' not in text


@pytest.mark.asyncio
async def test_hotpepper_created_is_idempotent_for_duplicate_source_ref():
    from app.services.hotpepper_mail import _handle_created

    db = AsyncMock()
    # duplicate check query returns an existing reservation -> should skip immediately
    db.execute.return_value = _FakeResult(one=SimpleNamespace(id=99))

    parsed = {
        "reservation_number": "HP-001",
        "patient_name": "田中太郎",
        "menu_name": "骨盤矯正",
        "practitioner_name": None,
        "start_time": datetime(2026, 4, 10, 10, 0),
        "end_time": datetime(2026, 4, 10, 11, 0),
        "coupon_name": None,
        "note": None,
        "amount": None,
    }

    result = await _handle_created(db, parsed)

    assert result["status"] == "skipped"
    assert result["reason"] == "duplicate"
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_chatbot_process_message_completes_on_create_reservation_tool():
    from app.services.chatbot_service import process_message

    session = SimpleNamespace(
        id="s1",
        status="active",
        reservation_id=None,
        messages=[],
    )
    db = AsyncMock()

    with patch("app.services.chatbot_service._check_message_rate", return_value=True), patch(
        "app.services.chatbot_service.get_session", new=AsyncMock(return_value=session)
    ), patch(
        "app.services.chatbot_service._get_setting",
        new=AsyncMock(side_effect=["system", "disabled"]),
    ), patch(
        "app.services.chatbot_service._call_llm",
        new=AsyncMock(
            side_effect=[
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "tc1",
                            "name": "create_reservation",
                            "arguments": {
                                "patient_name": "田中太郎",
                                "phone": "09012345678",
                                "date": "2026-04-15",
                                "start_time": "10:00",
                                "menu_id": 1,
                                "duration_minutes": 60,
                            },
                        }
                    ],
                },
                {"content": "予約を確定しました。", "tool_calls": []},
            ]
        ),
    ), patch(
        "app.services.chatbot_service.execute_tool",
        new=AsyncMock(
            return_value={
                "success": True,
                "reservation": {
                    "id": 555,
                    "date": "2026-04-15",
                    "start_time": "10:00",
                    "end_time": "11:00",
                },
            }
        ),
    ), patch("app.services.chatbot_service._check_reservation_rate", return_value=True):
        result = await process_message(db, session.id, "4/15 10時に予約したい", "127.0.0.1")

    assert result["reservation_created"]["id"] == 555
    assert session.status == "completed"
    assert session.reservation_id == 555


@pytest.mark.asyncio
async def test_transfer_candidates_marks_conflicted_practitioner_unavailable():
    from app.services.schedule_service import find_transfer_candidates

    p2 = SimpleNamespace(id=2, name="施術者A")
    p3 = SimpleNamespace(id=3, name="施術者B")

    db = AsyncMock()
    db.execute.side_effect = [
        _FakeResult(all_items=[p2, p3]),  # active practitioners (excluding original)
        _FakeResult(one=None),             # p2 conflict query -> no conflict
        _FakeResult(one=SimpleNamespace(id=1)),  # p3 conflict query -> conflicted
    ]

    with patch("app.services.schedule_service.is_practitioner_working", new=AsyncMock(return_value=(True, None, "default"))):
        candidates = await find_transfer_candidates(
            db=db,
            practitioner_id=1,
            target_date=datetime(2026, 4, 20).date(),
            start_time=datetime(2026, 4, 20, 10, 0),
            end_time=datetime(2026, 4, 20, 11, 0),
        )

    assert len(candidates) == 2
    assert candidates[0]["practitioner_id"] == 2
    assert candidates[0]["is_available"] is True
    assert candidates[1]["practitioner_id"] == 3
    assert candidates[1]["is_available"] is False


@pytest.mark.asyncio
async def test_hotpepper_poll_sends_recovered_after_failure_cycle():
    import app.services.hold_expiration as he
    from app.services.hold_expiration import poll_hotpepper_mail_job

    he._HOTPEPPER_POLL_FAILURE_STREAK = 0

    with patch(
        "app.services.hotpepper_mail.poll_hotpepper_mail_once",
        new=AsyncMock(side_effect=[{"status": "error", "reason": "x"}, {"status": "ok", "processed": 1}]),
    ), patch(
        "app.services.line_alerts.push_developer_sos_alert", new=AsyncMock(return_value=True)
    ) as mock_sos, patch(
        "app.services.line_alerts.push_developer_recovered_alert", new=AsyncMock(return_value=True)
    ) as mock_recovered:
        await poll_hotpepper_mail_job()
        await poll_hotpepper_mail_job()

    mock_sos.assert_awaited_once()
    mock_recovered.assert_awaited_once()
    assert he._HOTPEPPER_POLL_FAILURE_STREAK == 0
