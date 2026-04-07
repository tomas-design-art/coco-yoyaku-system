"""HotPepper IMAPポーリングの単体テスト"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class _AsyncSessionCtx:
    db: AsyncMock

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_poll_hotpepper_mail_once_processes_and_marks_seen():
    from app.services.hotpepper_mail import poll_hotpepper_mail_once

    mail = SimpleNamespace(
        uid="101",
        message_id="<mid-101@hotpepper.jp>",
        subject="予約通知",
        sender="noreply@hotpepper.jp",
        received_at=datetime(2026, 4, 3, 9, 0, 0),
        body="dummy body",
    )

    db = AsyncMock()
    adapter = MagicMock()
    adapter.fetch_unseen_hotpepper_mails.return_value = [mail]

    with patch("app.services.hotpepper_mail.settings.mail_provider", "icloud-imap"), patch(
        "app.services.hotpepper_mail.settings.icloud_email", "test@icloud.com"
    ), patch(
        "app.services.hotpepper_mail.settings.icloud_app_password", "app-password"
    ), patch("app.services.hotpepper_mail.IMAPAdapter", return_value=adapter), patch(
        "app.services.hotpepper_mail.async_session", return_value=_AsyncSessionCtx(db)
    ), patch(
        "app.services.hotpepper_mail._load_processed_mid_hashes", new=AsyncMock(return_value=[])
    ), patch(
        "app.services.hotpepper_mail._save_processed_mid_hashes", new=AsyncMock()
    ), patch(
        "app.services.hotpepper_mail._load_failed_mid_counts", new=AsyncMock(return_value={})
    ), patch(
        "app.services.hotpepper_mail._save_failed_mid_counts", new=AsyncMock()
    ) as mock_save_hashes, patch(
        "app.services.hotpepper_mail.process_hotpepper_email",
        new=AsyncMock(return_value={"status": "created", "reservation_id": 1}),
    ) as mock_process:
        result = await poll_hotpepper_mail_once()

    assert result["status"] == "ok"
    assert result["fetched"] == 1
    assert result["processed"] == 1
    assert result["failed"] == 0
    mock_process.assert_awaited_once_with(db, "dummy body")
    assert adapter.mark_seen.call_count == 1
    mock_save_hashes.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_hotpepper_mail_once_skips_already_processed_message_id():
    from app.services.hotpepper_mail import poll_hotpepper_mail_once, _message_id_hash

    message_id = "<mid-dup@hotpepper.jp>"
    mail = SimpleNamespace(
        uid="102",
        message_id=message_id,
        subject="予約通知",
        sender="noreply@hotpepper.jp",
        received_at=datetime(2026, 4, 3, 9, 10, 0),
        body="dummy body",
    )
    existing_hash = _message_id_hash(message_id)

    db = AsyncMock()
    adapter = MagicMock()
    adapter.fetch_unseen_hotpepper_mails.return_value = [mail]

    with patch("app.services.hotpepper_mail.settings.mail_provider", "icloud-imap"), patch(
        "app.services.hotpepper_mail.settings.icloud_email", "test@icloud.com"
    ), patch(
        "app.services.hotpepper_mail.settings.icloud_app_password", "app-password"
    ), patch("app.services.hotpepper_mail.IMAPAdapter", return_value=adapter), patch(
        "app.services.hotpepper_mail.async_session", return_value=_AsyncSessionCtx(db)
    ), patch(
        "app.services.hotpepper_mail._load_processed_mid_hashes", new=AsyncMock(return_value=[existing_hash])
    ), patch(
        "app.services.hotpepper_mail._save_processed_mid_hashes", new=AsyncMock()
    ), patch(
        "app.services.hotpepper_mail._load_failed_mid_counts", new=AsyncMock(return_value={})
    ), patch(
        "app.services.hotpepper_mail._save_failed_mid_counts", new=AsyncMock()
    ), patch(
        "app.services.hotpepper_mail.process_hotpepper_email", new=AsyncMock()
    ) as mock_process:
        result = await poll_hotpepper_mail_once()

    assert result["status"] == "ok"
    assert result["skipped"] == 1
    assert result["processed"] == 0
    mock_process.assert_not_awaited()
    assert adapter.mark_seen.call_count == 1


@pytest.mark.asyncio
async def test_poll_hotpepper_mail_once_dead_letters_after_retry_limit():
    from app.services.hotpepper_mail import poll_hotpepper_mail_once, _message_id_hash

    message_id = "<mid-dead@hotpepper.jp>"
    mail = SimpleNamespace(
        uid="103",
        message_id=message_id,
        subject="予約通知",
        sender="noreply@hotpepper.jp",
        received_at=datetime(2026, 4, 3, 9, 20, 0),
        body="bad body",
    )
    mh = _message_id_hash(message_id)

    db = AsyncMock()
    adapter = MagicMock()
    adapter.fetch_unseen_hotpepper_mails.return_value = [mail]

    with patch("app.services.hotpepper_mail.settings.mail_provider", "icloud-imap"), patch(
        "app.services.hotpepper_mail.settings.icloud_email", "test@icloud.com"
    ), patch(
        "app.services.hotpepper_mail.settings.icloud_app_password", "app-password"
    ), patch("app.services.hotpepper_mail.IMAPAdapter", return_value=adapter), patch(
        "app.services.hotpepper_mail.async_session", return_value=_AsyncSessionCtx(db)
    ), patch(
        "app.services.hotpepper_mail._load_processed_mid_hashes", new=AsyncMock(return_value=[])
    ), patch(
        "app.services.hotpepper_mail._save_processed_mid_hashes", new=AsyncMock()
    ), patch(
        "app.services.hotpepper_mail._load_failed_mid_counts", new=AsyncMock(return_value={mh: 2})
    ), patch(
        "app.services.hotpepper_mail._save_failed_mid_counts", new=AsyncMock()
    ), patch(
        "app.services.hotpepper_mail.process_hotpepper_email", new=AsyncMock(return_value={"status": "error", "reason": "parse"})
    ):
        result = await poll_hotpepper_mail_once()

    assert result["status"] == "ok"
    assert result["failed"] == 1
    assert result["dead_lettered"] == 1
    assert adapter.mark_seen.call_count == 1
