"""チャネル横断の患者同一人物マッチング & find-or-create ユーティリティ."""

import logging
import re
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient

logger = logging.getLogger(__name__)


def normalize_phone(v: str | None) -> str | None:
    """電話番号の正規化: ハイフン除去、全角→半角"""
    if not v:
        return None
    v = v.translate(str.maketrans("０１２３４５６７８９－", "0123456789-"))
    v = v.replace("-", "").replace("ー", "").replace(" ", "").replace("\u3000", "")
    return v.strip() or None


def normalize_name(v: str | None) -> str:
    """名前の正規化: 全角スペース→半角、連続スペース除去、strip、lower"""
    if not v:
        return ""
    s = v.replace("\u3000", " ")
    s = re.sub(r"\s+", "", s)  # スペースを全て除去して比較
    return s.strip().lower()


def split_name_if_delimited(v: str | None) -> tuple[str | None, str | None]:
    """区切りがある場合のみ姓名分割する（誤分割を避けるため）。"""
    if not v:
        return None, None
    s = v.replace("\u3000", " ").strip()
    parts = [p for p in re.split(r"\s+", s) if p]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return None, None


async def _generate_patient_number(db: AsyncSession) -> str:
    """P000001 形式で一意な患者番号を自動採番"""
    result = await db.execute(
        select(func.max(Patient.patient_number))
        .where(Patient.patient_number.op("~")(r"^P\d+$"))
    )
    max_num = result.scalar()
    if max_num:
        next_val = int(max_num[1:]) + 1
    else:
        next_val = 1
    return f"P{next_val:06d}"


async def find_existing_patient(
    db: AsyncSession,
    *,
    name: str | None = None,
    phone: str | None = None,
    line_id: str | None = None,
) -> Patient | None:
    """電話番号 → line_id → 名前+電話 の優先度で既存患者を検索する。

    Returns: 見つかった Patient or None
    """
    norm_phone = normalize_phone(phone)
    norm_name = normalize_name(name)

    # 1) 電話番号(正規化)で検索 ─ 最も信頼度が高い
    if norm_phone:
        result = await db.execute(
            select(Patient).where(Patient.phone.isnot(None))
        )
        for p in result.scalars().all():
            if normalize_phone(p.phone) == norm_phone:
                logger.info("患者マッチ(電話): id=%d name=%s", p.id, p.name)
                return p

    # 2) LINE ID で検索
    if line_id:
        result = await db.execute(
            select(Patient).where(Patient.line_id == line_id).limit(1)
        )
        p = result.scalar_one_or_none()
        if p:
            logger.info("患者マッチ(LINE ID): id=%d name=%s", p.id, p.name)
            return p

    # 3) 名前の正規化一致 (電話番号なし＋LINE IDなしの場合のフォールバック)
    #    同姓同名リスクがあるため、名前だけでは作成済み患者数1件の場合のみマッチ
    if norm_name:
        result = await db.execute(select(Patient))
        candidates = [
            p for p in result.scalars().all()
            if normalize_name(p.name) == norm_name
        ]
        if len(candidates) == 1:
            logger.info("患者マッチ(名前): id=%d name=%s", candidates[0].id, candidates[0].name)
            return candidates[0]

    return None


async def find_name_candidates(db: AsyncSession, name: str, limit: int = 5) -> list[Patient]:
    """正規化した名前一致の候補を返す（同姓同名確認用）。"""
    norm_name = normalize_name(name)
    if not norm_name:
        return []
    result = await db.execute(select(Patient).order_by(Patient.id.desc()))
    candidates = [
        p for p in result.scalars().all()
        if normalize_name(p.name) == norm_name
    ]
    return candidates[:limit]


def match_identity_token(patient: Patient, token: str) -> bool:
    """本人確認入力（電話番号 or 生年月日）で候補患者と一致するか判定する。"""
    t = (token or "").strip()
    if not t:
        return False

    # 電話番号一致
    token_phone = normalize_phone(t)
    if token_phone and patient.phone and normalize_phone(patient.phone) == token_phone:
        return True

    # 生年月日一致 (YYYY-MM-DD)
    if patient.birth_date:
        if t == patient.birth_date.isoformat():
            return True

    return False


async def find_or_create_patient(
    db: AsyncSession,
    *,
    name: str | None = None,
    phone: str | None = None,
    line_id: str | None = None,
    auto_number: bool = True,
) -> Patient:
    """既存患者を検索し、なければ新規作成。見つかった場合は不足フィールドを補完する。"""

    patient = await find_existing_patient(db, name=name, phone=phone, line_id=line_id)

    if patient:
        # 既存患者の不足フィールドを補完
        updated = False
        if name and patient.name in {None, "", "不明", "LINE患者"}:
            patient.name = name
            updated = True
        if phone and not patient.phone:
            patient.phone = normalize_phone(phone)
            updated = True
        if line_id and not patient.line_id:
            patient.line_id = line_id
            updated = True
        if not patient.patient_number and auto_number:
            patient.patient_number = await _generate_patient_number(db)
            updated = True
        if updated:
            await db.flush()
        return patient

    # 新規作成
    return await create_new_patient(
        db,
        name=name,
        phone=phone,
        line_id=line_id,
        auto_number=auto_number,
    )


async def create_new_patient(
    db: AsyncSession,
    *,
    name: str | None = None,
    phone: str | None = None,
    line_id: str | None = None,
    auto_number: bool = True,
) -> Patient:
    """既存照合せずに患者を新規作成する。"""
    norm_phone = normalize_phone(phone)
    patient_number = await _generate_patient_number(db) if auto_number else None

    last_name, first_name = split_name_if_delimited(name)
    registration_mode = "split" if (last_name and first_name) else "full_name"

    patient = Patient(
        name=name or "不明",
        last_name=last_name,
        first_name=first_name,
        phone=norm_phone,
        line_id=line_id,
        patient_number=patient_number,
        registration_mode=registration_mode,
    )
    db.add(patient)
    await db.flush()
    logger.info("患者新規作成: id=%d name=%s phone=%s line_id=%s", patient.id, patient.name, norm_phone, line_id)
    return patient
