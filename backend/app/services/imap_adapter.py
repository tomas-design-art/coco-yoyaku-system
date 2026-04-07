"""IMAPアダプター: iCloud等からHotPepperメールを取得する。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
import imaplib
import logging
import re

logger = logging.getLogger(__name__)


@dataclass
class IMAPFetchedMail:
    uid: str
    message_id: str
    subject: str
    sender: str
    received_at: datetime | None
    body: str


class IMAPAdapter:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        mailbox: str = "INBOX",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mailbox = mailbox
        self._client: imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        self._client = imaplib.IMAP4_SSL(self.host, self.port)
        self._client.login(self.username, self.password)
        self._client.select(self.mailbox)

    def close(self) -> None:
        if not self._client:
            return
        try:
            self._client.close()
        except Exception:
            pass
        try:
            self._client.logout()
        except Exception:
            pass
        self._client = None

    def fetch_unseen_hotpepper_mails(
        self,
        sender_filters: list[str],
        *,
        limit: int = 50,
    ) -> list[IMAPFetchedMail]:
        if not self._client:
            raise RuntimeError("IMAP client is not connected")

        status, data = self._client.uid("search", None, "UNSEEN")
        if status != "OK":
            logger.warning("IMAP search failed: status=%s", status)
            return []

        uids = data[0].split() if data and data[0] else []
        fetched: list[IMAPFetchedMail] = []

        for uid_b in uids[-limit:]:
            uid = uid_b.decode("utf-8", errors="ignore")
            status, msg_data = self._client.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not msg_data:
                continue

            raw = b""
            for part in msg_data:
                if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
                    raw = bytes(part[1])
                    break
            if not raw:
                continue

            msg = message_from_bytes(raw)
            sender = self._decode_header(msg.get("From", ""))
            if not self._matches_sender(sender, sender_filters):
                continue

            message_id = (msg.get("Message-ID") or "").strip()
            subject = self._decode_header(msg.get("Subject", ""))
            received_at = self._parse_received_at(msg.get("Date"))
            body = self._extract_body_text(msg)

            fetched.append(
                IMAPFetchedMail(
                    uid=uid,
                    message_id=message_id,
                    subject=subject,
                    sender=sender,
                    received_at=received_at,
                    body=body,
                )
            )

        fetched.sort(key=lambda m: int(m.uid) if m.uid.isdigit() else 0)
        return fetched

    def mark_seen(self, uid: str) -> None:
        if not self._client:
            raise RuntimeError("IMAP client is not connected")
        self._client.uid("store", uid, "+FLAGS", "(\\Seen)")

    @staticmethod
    def _decode_header(value: str) -> str:
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    @staticmethod
    def _parse_received_at(date_header: str | None) -> datetime | None:
        if not date_header:
            return None
        try:
            return parsedate_to_datetime(date_header)
        except Exception:
            return None

    @staticmethod
    def _matches_sender(sender: str, sender_filters: list[str]) -> bool:
        if not sender_filters:
            return True
        s = sender.lower()
        return any(f.lower() in s for f in sender_filters)

    @classmethod
    def _extract_body_text(cls, msg) -> str:
        if msg.is_multipart():
            plain_parts: list[str] = []
            html_parts: list[str] = []

            for part in msg.walk():
                ctype = (part.get_content_type() or "").lower()
                disp = (part.get("Content-Disposition") or "").lower()
                if "attachment" in disp:
                    continue
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="ignore")
                if ctype == "text/plain":
                    plain_parts.append(text)
                elif ctype == "text/html":
                    html_parts.append(text)

            if plain_parts:
                return "\n".join(plain_parts).strip()
            if html_parts:
                return cls._html_to_text("\n".join(html_parts))
            return ""

        payload = msg.get_payload(decode=True)
        if payload is None:
            return ""
        charset = msg.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="ignore")
        if (msg.get_content_type() or "").lower() == "text/html":
            return cls._html_to_text(text)
        return text.strip()

    @staticmethod
    def _html_to_text(html: str) -> str:
        # 依存を増やさず簡易テキスト化
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
