"""チャネル横断の患者同一人物マッチング & find-or-create ユーティリティ."""

import logging
import re
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.patient import Patient

logger = logging.getLogger(__name__)


def normalize_phone(v: str | None) -> str | None:
    """電話番号の正規化: ハイフン除去、全角→半角、+81→0 変換"""
    if not v:
        return None
    v = v.translate(str.maketrans("０１２３４５６７８９－＋", "0123456789-+"))
    v = v.replace("-", "").replace("ー", "").replace(" ", "").replace("\u3000", "")
    v = v.strip()
    # +81 国際番号表記を 0 始まりに変換
    if v.startswith("+81"):
        v = "0" + v[3:]
    elif v.startswith("81") and len(v) >= 12:
        v = "0" + v[2:]
    return v or None


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
    """名前+電話 → 電話のみ(単一) → LINE ID → 名前のみ の優先度で既存患者を検索する。

    Returns: 見つかった Patient or None
    """
    norm_phone = normalize_phone(phone)
    norm_name = normalize_name(name)

    # 全患者を1回だけ取得して以降のチェックで再利用する
    all_patients = (await db.execute(select(Patient))).scalars().all()

    # 1) 名前 + 電話番号の組み合わせ検索 ─ 最も信頼度が高い
    #    家族で同じ電話を共有するケースがあるため、電話だけではマッチしない
    if norm_name and norm_phone:
        for p in all_patients:
            if not p.phone or normalize_phone(p.phone) != norm_phone:
                continue
            if _name_matches_patient(norm_name, p):
                logger.info("患者マッチ(名前+電話): id=%d name=%s phone=%s", p.id, p.name, p.phone)
                return p

    # 1.5) 電話番号のみマッチ ─ 同一電話番号の患者が1人しかいなければ同一人物と判定
    #    名前表記ゆれ・チャネル違いでも電話番号が同じなら高確率で本人
    if norm_phone:
        phone_candidates = [
            p for p in all_patients
            if p.phone and normalize_phone(p.phone) == norm_phone
        ]
        if len(phone_candidates) == 1:
            logger.info(
                "患者マッチ(電話のみ): id=%d name=%s phone=%s (入力名=%s)",
                phone_candidates[0].id, phone_candidates[0].name,
                phone_candidates[0].phone, name,
            )
            return phone_candidates[0]
        if len(phone_candidates) > 1 and norm_name:
            # 電話が同じ患者が複数 → 名前の部分一致でさらに絞る
            for p in phone_candidates:
                p_name = normalize_name(p.name)
                p_combined = normalize_name(
                    f"{p.last_name or ''}{p.first_name or ''}"
                )
                if (p_name and norm_name in p_name) or (p_combined and norm_name in p_combined):
                    logger.info(
                        "患者マッチ(電話+名前部分一致): id=%d name=%s phone=%s",
                        p.id, p.name, p.phone,
                    )
                    return p
                if (p_name and p_name in norm_name) or (p_combined and p_combined in norm_name):
                    logger.info(
                        "患者マッチ(電話+名前部分一致逆方向): id=%d name=%s phone=%s",
                        p.id, p.name, p.phone,
                    )
                    return p

    # 2) LINE ID で検索
    if line_id:
        for p in all_patients:
            if p.line_id and p.line_id == line_id:
                logger.info("患者マッチ(LINE ID): id=%d name=%s", p.id, p.name)
                return p

    # 3) 名前の正規化一致 (電話番号なし＋LINE IDなしの場合のフォールバック)
    #    同姓同名リスクがあるため、名前だけでは作成済み患者数1件の場合のみマッチ
    if norm_name:
        candidates = [p for p in all_patients if _name_matches_patient(norm_name, p)]
        if len(candidates) == 1:
            logger.info("患者マッチ(名前): id=%d name=%s", candidates[0].id, candidates[0].name)
            return candidates[0]
        if len(candidates) > 1:
            logger.warning(
                "患者マッチ(名前): 同姓同名が%d件のためスキップ name=%s ids=%s",
                len(candidates), name, [c.id for c in candidates],
            )

    logger.info("患者マッチ: 該当なし name=%s phone=%s line_id=%s", name, phone, line_id)

    return None


def _name_matches_patient(norm_name: str, patient: Patient) -> bool:
    """正規化済みの名前が患者レコードのいずれかの名前列と一致するか判定する。

    比較対象:
      - name 列 (合成済みフルネーム)
      - last_name + first_name (姓名分離保存)
      - last_name のみ / first_name のみ (片方だけ入っている場合)
    """
    if normalize_name(patient.name) == norm_name:
        return True
    # last_name + first_name の結合比較
    if patient.last_name or patient.first_name:
        combined = normalize_name(
            f"{patient.last_name or ''}{patient.first_name or ''}"
        )
        if combined == norm_name:
            return True
    return False


async def find_name_candidates(db: AsyncSession, name: str, limit: int = 5) -> list[Patient]:
    """正規化した名前一致の候補を返す（同姓同名確認用）。"""
    norm_name = normalize_name(name)
    if not norm_name:
        return []
    result = await db.execute(select(Patient).order_by(Patient.id.desc()))
    candidates = [
        p for p in result.scalars().all()
        if _name_matches_patient(norm_name, p)
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
    reading: str | None = None,
    auto_number: bool = True,
    last_name: str | None = None,
    first_name: str | None = None,
    last_name_kana: str | None = None,
    first_name_kana: str | None = None,
    full_name: str | None = None,
    email: str | None = None,
    notes: str | None = None,
) -> Patient:
    """既存患者を検索し、なければ新規作成。見つかった場合は不足フィールドを補完する。"""

    # 検索用の name を合成（full_name または 姓+名 または name）
    search_name = (
        full_name
        or (f"{last_name or ''} {first_name or ''}".strip() if (last_name or first_name) else None)
        or name
    )

    patient = await find_existing_patient(db, name=search_name, phone=phone, line_id=line_id)

    if patient:
        # 既存患者の不足フィールドを補完
        updated = False
        if search_name and patient.name in {None, "", "不明", "LINE患者"}:
            patient.name = search_name
            updated = True
        if phone and not patient.phone:
            patient.phone = normalize_phone(phone)
            updated = True
        if line_id and not patient.line_id:
            patient.line_id = line_id
            updated = True
        if reading and not patient.reading:
            patient.reading = reading
            updated = True
        if last_name and not patient.last_name:
            patient.last_name = last_name.strip()
            updated = True
        if first_name and not patient.first_name:
            patient.first_name = first_name.strip()
            updated = True
        if last_name_kana and not patient.last_name_kana:
            patient.last_name_kana = last_name_kana.strip()
            updated = True
        if first_name_kana and not patient.first_name_kana:
            patient.first_name_kana = first_name_kana.strip()
            updated = True
        if email and not patient.email:
            patient.email = email.strip()
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
        name=search_name,
        phone=phone,
        line_id=line_id,
        reading=reading,
        auto_number=auto_number,
        last_name=last_name,
        first_name=first_name,
        last_name_kana=last_name_kana,
        first_name_kana=first_name_kana,
        full_name=full_name,
        email=email,
        notes=notes,
    )


async def create_new_patient(
    db: AsyncSession,
    *,
    name: str | None = None,
    phone: str | None = None,
    line_id: str | None = None,
    reading: str | None = None,
    auto_number: bool = True,
    last_name: str | None = None,
    first_name: str | None = None,
    last_name_kana: str | None = None,
    first_name_kana: str | None = None,
    full_name: str | None = None,
    email: str | None = None,
    notes: str | None = None,
) -> Patient:
    """既存照合せずに患者を新規作成する。

    姓名分割入力 (last_name/first_name) が指定されていればそれを優先。
    full_name が指定されていれば full_name モードで登録（外国人名・長い名前用）。
    name だけの場合は従来通り区切りで分割試行する。
    """
    norm_phone = normalize_phone(phone)
    patient_number = await _generate_patient_number(db) if auto_number else None

    # ── 名前フィールドの解決 ──
    if full_name and full_name.strip():
        # フルネームモード（外国人名など）: 分割せず name のみ保持
        resolved_name = full_name.strip()
        resolved_last = None
        resolved_first = None
        registration_mode = "full_name"
    elif last_name or first_name:
        # 姓名分割モード
        resolved_last = (last_name or "").strip() or None
        resolved_first = (first_name or "").strip() or None
        resolved_name = " ".join(filter(None, [resolved_last, resolved_first])) or (name or "不明")
        registration_mode = "split"
    else:
        # name 文字列のみ: 既存動作
        resolved_last, resolved_first = split_name_if_delimited(name)
        resolved_name = name or "不明"
        registration_mode = "split" if (resolved_last and resolved_first) else "full_name"

    # ── フリガナの解決 ──
    resolved_last_kana = (last_name_kana or "").strip() or None
    resolved_first_kana = (first_name_kana or "").strip() or None
    resolved_reading = reading
    if not resolved_reading and (resolved_last_kana or resolved_first_kana):
        resolved_reading = "".join(filter(None, [resolved_last_kana, resolved_first_kana]))

    patient = Patient(
        name=resolved_name,
        last_name=resolved_last,
        first_name=resolved_first,
        last_name_kana=resolved_last_kana,
        first_name_kana=resolved_first_kana,
        reading=resolved_reading,
        phone=norm_phone,
        email=(email.strip() if email else None) or None,
        line_id=line_id,
        notes=(notes.strip() if notes else None) or None,
        patient_number=patient_number,
        registration_mode=registration_mode,
    )
    db.add(patient)
    await db.flush()
    logger.info(
        "患者新規作成: id=%d name=%s mode=%s phone=%s line_id=%s",
        patient.id, patient.name, registration_mode, norm_phone, line_id,
    )
    return patient
