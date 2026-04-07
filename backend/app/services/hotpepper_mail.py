"""HotPepperメール取得アダプター + 予約登録サービス"""
import asyncio
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.menu import Menu
from app.models.patient import Patient
from app.models.practitioner import Practitioner
from app.models.reservation import Reservation
from app.models.setting import Setting
from app.services.notification_service import create_notification
from app.agents.mail_parser import parse_hotpepper_mail
from app.services.imap_adapter import IMAPAdapter, IMAPFetchedMail
from app.database import async_session

logger = logging.getLogger(__name__)

PROCESSED_MID_HASHES_KEY = "hotpepper_processed_mid_hashes"
FAILED_MID_COUNTS_KEY = "hotpepper_failed_mid_counts"
MAX_PROCESSED_HASHES = 1000
MAX_FAILED_TRACKED = 2000
DEAD_LETTER_RETRY_LIMIT = 3


@dataclass
class Email:
    subject: str
    body: str
    sender: str
    received_at: datetime
    message_id: str


class MailFetcher(ABC):
    """メール取得の抽象クラス"""

    @abstractmethod
    async def fetch_new_emails(self, since: datetime) -> list[Email]:
        ...


class GmailFetcher(MailFetcher):
    """Gmail API (OAuth2) でメールを取得"""

    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path

    async def fetch_new_emails(self, since: datetime) -> list[Email]:
        # Gmail API実装（OAuth2設定後に有効化）
        logger.info("Gmail fetcher not yet configured")
        return []


class IMAPFetcher(MailFetcher):
    """汎用IMAP でメールを取得"""

    def __init__(self, host: str, port: int, username: str, password: str, use_ssl: bool = True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl

    async def fetch_new_emails(self, since: datetime) -> list[Email]:
        # IMAP実装
        logger.info("IMAP fetcher not yet configured")
        return []


def get_mail_fetcher(provider: str = "gmail") -> MailFetcher:
    """環境変数に基づいてメールフェッチャーを返す"""
    if provider == "gmail":
        return GmailFetcher()
    elif provider == "imap":
        return IMAPFetcher(
            host="imap.example.com",
            port=993,
            username="",
            password="",
        )
    else:
        raise ValueError(f"Unknown mail provider: {provider}")


def _message_id_hash(message_id: str) -> str:
    return hashlib.sha1(message_id.encode("utf-8", errors="ignore")).hexdigest()[:12]


async def _get_setting(db: AsyncSession, key: str, default: str = "") -> str:
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else default


async def _set_setting(db: AsyncSession, key: str, value: str):
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    await db.flush()


async def _load_processed_mid_hashes(db: AsyncSession) -> list[str]:
    raw = await _get_setting(db, PROCESSED_MID_HASHES_KEY, "")
    if not raw:
        return []
    return [x for x in raw.split(",") if x]


async def _save_processed_mid_hashes(db: AsyncSession, hashes: list[str]):
    compact = ",".join(hashes[-MAX_PROCESSED_HASHES:])
    await _set_setting(db, PROCESSED_MID_HASHES_KEY, compact)


async def _load_failed_mid_counts(db: AsyncSession) -> dict[str, int]:
    raw = await _get_setting(db, FAILED_MID_COUNTS_KEY, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in data.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                continue
        return out
    except Exception:
        logger.warning("failed to parse %s; reset", FAILED_MID_COUNTS_KEY)
        return {}


async def _save_failed_mid_counts(db: AsyncSession, counts: dict[str, int]):
    items = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:MAX_FAILED_TRACKED]
    compact = json.dumps({k: v for k, v in items}, ensure_ascii=False)
    await _set_setting(db, FAILED_MID_COUNTS_KEY, compact)


def _sender_filters_from_settings() -> list[str]:
    if settings.hotpepper_sender_filters:
        return [x.strip() for x in settings.hotpepper_sender_filters.split(",") if x.strip()]
    return ["hotpepper.jp", "beauty.hotpepper.jp", "salonboard"]


async def poll_hotpepper_mail_once() -> dict:
    """iCloud/IMAP からHotPepperメールを取得して処理する。"""
    if settings.mail_provider.lower() not in {"imap", "icloud", "icloud_imap", "icloud-imap"}:
        return {"status": "skipped", "reason": f"mail_provider={settings.mail_provider}"}

    if not settings.icloud_email or not settings.icloud_app_password:
        logger.warning("ICLOUD_EMAIL/ICLOUD_APP_PASSWORD が未設定のためポーリングをスキップ")
        return {"status": "skipped", "reason": "icloud_credentials_missing"}

    adapter = IMAPAdapter(
        host=settings.imap_host,
        port=settings.imap_port,
        username=settings.icloud_email,
        password=settings.icloud_app_password,
        mailbox=settings.imap_mailbox,
    )

    retries = max(1, settings.hotpepper_poll_max_retries)
    base_delay = max(1, settings.hotpepper_poll_retry_base_seconds)
    emails: list[IMAPFetchedMail] = []
    sender_filters = _sender_filters_from_settings()

    for attempt in range(1, retries + 1):
        try:
            await asyncio.to_thread(adapter.connect)
            emails = await asyncio.to_thread(
                adapter.fetch_unseen_hotpepper_mails,
                sender_filters,
                limit=settings.hotpepper_poll_fetch_limit,
            )
            break
        except Exception as e:
            logger.exception("HotPepper IMAP poll failed (attempt=%s/%s): %s", attempt, retries, e)
            if attempt >= retries:
                return {"status": "error", "reason": str(e), "attempts": attempt}
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))

    processed = 0
    skipped = 0
    failed = 0
    dead_lettered = 0

    try:
        async with async_session() as db:
            processed_hashes = await _load_processed_mid_hashes(db)
            failed_counts = await _load_failed_mid_counts(db)
            seen_set = set(processed_hashes)

            for mail in emails:
                mid = mail.message_id or f"uid:{mail.uid}"
                mh = _message_id_hash(mid)

                if mh in seen_set:
                    skipped += 1
                    await asyncio.to_thread(adapter.mark_seen, mail.uid)
                    continue

                result = await process_hotpepper_email(db, mail.body)
                status = result.get("status")
                if status in {"created", "changed", "cancelled", "skipped"}:
                    processed += 1
                    seen_set.add(mh)
                    failed_counts.pop(mh, None)
                    await asyncio.to_thread(adapter.mark_seen, mail.uid)
                else:
                    failed += 1
                    retries = failed_counts.get(mh, 0) + 1
                    failed_counts[mh] = retries
                    if retries >= DEAD_LETTER_RETRY_LIMIT:
                        dead_lettered += 1
                        seen_set.add(mh)
                        logger.error(
                            "HotPepper mail dead-lettered: uid=%s message_id=%s hash=%s retries=%s",
                            mail.uid,
                            mail.message_id,
                            mh,
                            retries,
                        )
                        await asyncio.to_thread(adapter.mark_seen, mail.uid)
                        failed_counts.pop(mh, None)

            await _save_processed_mid_hashes(db, list(seen_set))
            await _save_failed_mid_counts(db, failed_counts)
            await db.commit()
    finally:
        await asyncio.to_thread(adapter.close)

    return {
        "status": "ok",
        "fetched": len(emails),
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "dead_lettered": dead_lettered,
    }


# ---------------------------------------------------------------------------
# HotPepper メール → 予約登録
# ---------------------------------------------------------------------------


async def process_hotpepper_email(db: AsyncSession, email_body: str) -> dict:
    """HotPepper メール本文を解析し、予約を登録/更新/キャンセルする。

    Returns:
        dict: {"status": "created"|"cancelled"|"changed"|"skipped"|"error", ...}
    """
    logger.info("HotPepper メール受信 — パース開始")

    # ── 1. パース ──
    try:
        parsed = parse_hotpepper_mail(email_body)
        logger.info(
            f"パース成功: event={parsed['event_type']}, "
            f"予約番号={parsed['reservation_number']}, 患者名={parsed['patient_name']}"
        )
    except ValueError as e:
        logger.error(f"パース失敗: {e}")
        try:
            from app.services.line_alerts import push_admin_hotpepper_failure

            await push_admin_hotpepper_failure(str(e), email_body)
        except Exception as notify_err:
            logger.error("HotPepper parse failure LINE通知に失敗: %s", notify_err)
        return {"status": "error", "reason": str(e)}

    event_type = parsed["event_type"]

    # ── イベント種別ルーティング ──
    if event_type == "cancelled":
        return await _handle_cancelled(db, parsed)
    elif event_type == "changed":
        return await _handle_changed(db, parsed)
    else:
        return await _handle_created(db, parsed)


async def _handle_created(db: AsyncSession, parsed: dict) -> dict:
    """新規予約の登録"""
    # ── 重複チェック ──
    existing = await db.execute(
        select(Reservation).where(Reservation.source_ref == parsed["reservation_number"])
    )
    if existing.scalar_one_or_none():
        logger.info(f"重複スキップ: source_ref={parsed['reservation_number']} は登録済み")
        return {"status": "skipped", "reason": "duplicate", "reservation_number": parsed["reservation_number"]}

    patient = await _find_or_create_patient(db, parsed["patient_name"])
    menu_id, menu_note = await _match_menu(db, parsed.get("menu_name"))
    practitioner_id, prac_note = await _assign_practitioner(db, parsed.get("practitioner_name"))

    notes = _build_notes(parsed, menu_note, prac_note)

    reservation = Reservation(
        patient_id=patient.id,
        practitioner_id=practitioner_id,
        menu_id=menu_id,
        start_time=parsed["start_time"],
        end_time=parsed["end_time"],
        status="CONFIRMED",
        channel="HOTPEPPER",
        source_ref=parsed["reservation_number"],
        notes=notes,
        hotpepper_synced=True,
    )
    db.add(reservation)
    await db.flush()

    logger.info(f"予約作成: id={reservation.id}, source_ref={parsed['reservation_number']}")

    await create_notification(
        db,
        "new_reservation",
        f"HotPepper予約: {parsed['patient_name']} "
        f"{parsed['start_time'].strftime('%m/%d %H:%M')}-{parsed['end_time'].strftime('%H:%M')} "
        f"{parsed.get('menu_name') or '(メニュー不明)'}",
        reservation.id,
    )

    await db.commit()
    return {
        "status": "created",
        "reservation_id": reservation.id,
        "reservation_number": parsed["reservation_number"],
    }


async def _handle_cancelled(db: AsyncSession, parsed: dict) -> dict:
    """既存予約のキャンセル処理"""
    ref = parsed["reservation_number"]

    result = await db.execute(
        select(Reservation).where(Reservation.source_ref == ref)
    )
    reservation = result.scalar_one_or_none()

    if not reservation:
        logger.warning(f"キャンセル対象の予約が見つかりません: source_ref={ref}")
        return {"status": "skipped", "reason": "not_found", "reservation_number": ref}

    if reservation.status == "CANCELLED":
        logger.info(f"既にキャンセル済み: source_ref={ref}")
        return {"status": "skipped", "reason": "already_cancelled", "reservation_number": ref}

    old_status = reservation.status
    reservation.status = "CANCELLED"
    reservation.notes = (reservation.notes or "") + " / HPキャンセル通知により自動キャンセル"

    logger.info(f"予約キャンセル: id={reservation.id}, {old_status}→CANCELLED, source_ref={ref}")

    await create_notification(
        db,
        "reservation_cancelled",
        f"HotPepperキャンセル: {parsed['patient_name']} "
        f"{parsed['start_time'].strftime('%m/%d %H:%M')} "
        f"{parsed.get('menu_name') or ''}",
        reservation.id,
    )

    await db.commit()
    return {
        "status": "cancelled",
        "reservation_id": reservation.id,
        "reservation_number": ref,
    }


async def _handle_changed(db: AsyncSession, parsed: dict) -> dict:
    """既存予約の変更処理"""
    ref = parsed["reservation_number"]

    result = await db.execute(
        select(Reservation).where(Reservation.source_ref == ref)
    )
    reservation = result.scalar_one_or_none()

    if not reservation:
        # 変更通知だが元予約が未登録 → 新規として登録
        logger.info(f"変更対象が未登録のため新規作成: source_ref={ref}")
        return await _handle_created(db, parsed)

    # 変更内容を更新
    reservation.start_time = parsed["start_time"]
    reservation.end_time = parsed["end_time"]

    menu_id, menu_note = await _match_menu(db, parsed.get("menu_name"))
    if menu_id:
        reservation.menu_id = menu_id

    practitioner_id, prac_note = await _assign_practitioner(db, parsed.get("practitioner_name"))
    reservation.practitioner_id = practitioner_id

    notes = _build_notes(parsed, menu_note, prac_note, prefix="HotPepper変更予約")
    reservation.notes = notes

    logger.info(f"予約変更: id={reservation.id}, source_ref={ref}")

    await create_notification(
        db,
        "reservation_changed",
        f"HotPepper変更: {parsed['patient_name']} "
        f"{parsed['start_time'].strftime('%m/%d %H:%M')}-{parsed['end_time'].strftime('%H:%M')} "
        f"{parsed.get('menu_name') or ''}",
        reservation.id,
    )

    await db.commit()
    return {
        "status": "changed",
        "reservation_id": reservation.id,
        "reservation_number": ref,
    }


def _build_notes(parsed: dict, menu_note: str | None, prac_note: str | None,
                 prefix: str = "HotPepper予約") -> str:
    """備考文字列を組み立て"""
    parts = [prefix]
    if parsed.get("coupon_name"):
        parts.append(f"クーポン: {parsed['coupon_name']}")
    if parsed.get("note"):
        parts.append(f"要望: {parsed['note']}")
    if parsed.get("amount") is not None:
        parts.append(f"金額: {parsed['amount']}円")
    if menu_note:
        parts.append(menu_note)
    if prac_note:
        parts.append(prac_note)
    return " / ".join(parts)


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


async def _find_or_create_patient(db: AsyncSession, name: str) -> Patient:
    """患者を名前で検索。見つからなければ新規作成。"""
    result = await db.execute(
        select(Patient).where(Patient.name == name)
    )
    patient = result.scalar_one_or_none()
    if patient:
        return patient

    logger.info(f"患者新規作成: {name}")
    patient = Patient(name=name)
    db.add(patient)
    await db.flush()
    return patient


async def _match_menu(db: AsyncSession, menu_name: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    """メニュー名でシステム内メニューを検索。
    Returns: (menu_id or None, 不一致時の注記 or None)
    """
    if not menu_name:
        return None, None

    # 完全一致
    result = await db.execute(
        select(Menu).where(Menu.name == menu_name, Menu.is_active == True)
    )
    menu = result.scalar_one_or_none()
    if menu:
        return menu.id, None

    # 部分一致: メニュー名がシステム側に含まれるか
    result = await db.execute(
        select(Menu).where(Menu.is_active == True)
    )
    menus = result.scalars().all()
    for m in menus:
        if m.name in menu_name or menu_name in m.name:
            return m.id, None

    return None, f"HPメニュー名: {menu_name}"


async def _assign_practitioner(db: AsyncSession, name: Optional[str]) -> tuple[int, Optional[str]]:
    """施術者を名前で検索。指名なし or 見つからない場合はデフォルト施術者を割り当て。
    Returns: (practitioner_id, 注記 or None)
    """
    note = None

    if name:
        result = await db.execute(
            select(Practitioner).where(Practitioner.name == name, Practitioner.is_active == True)
        )
        prac = result.scalar_one_or_none()
        if prac:
            return prac.id, None
        note = f"指名「{name}」が見つからずデフォルト割当"
        logger.warning(note)

    # デフォルト: display_order 最小のアクティブ施術者
    result = await db.execute(
        select(Practitioner).where(Practitioner.is_active == True).order_by(Practitioner.display_order).limit(1)
    )
    prac = result.scalar_one_or_none()
    if prac:
        return prac.id, note

    raise ValueError("アクティブな施術者が登録されていません")
