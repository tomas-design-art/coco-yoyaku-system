from pydantic import BaseModel, field_validator, model_validator
from datetime import date, datetime
from typing import Optional, Literal
import re


def _normalize_name(v: str) -> str:
    """名前の正規化: 全角スペース→半角、連続スペース除去、前後trim"""
    v = v.replace("\u3000", " ")  # 全角→半角スペース
    v = re.sub(r"\s+", " ", v)   # 連続スペース除去
    return v.strip()


def _normalize_phone(v: str | None) -> str | None:
    """電話番号の正規化: ハイフン除去、全角→半角"""
    if not v:
        return None
    v = v.translate(str.maketrans("０１２３４５６７８９－", "0123456789-"))
    v = v.replace("-", "").replace("ー", "").replace(" ", "").replace("\u3000", "")
    return v.strip() or None


def _validate_name_length(v: str, label: str = "名前") -> str:
    if len(v) > 100:
        raise ValueError(f"{label}は100文字以内で入力してください")
    return v


def build_name(mode: str, last_name: str | None, middle_name: str | None,
               first_name: str | None, full_name_value: str | None) -> str:
    """registration_mode に応じて name を組み立てる"""
    if mode == "full_name":
        return _normalize_name(full_name_value or "")
    parts = [p for p in [last_name, middle_name, first_name] if p]
    return " ".join(parts)


# ──────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────
class PatientCreate(BaseModel):
    registration_mode: Literal["split", "full_name"] = "split"
    # split mode fields
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    first_name: Optional[str] = None
    # full_name mode: name に直接格納
    full_name: Optional[str] = None
    # 共通
    reading: Optional[str] = None
    last_name_kana: Optional[str] = None
    first_name_kana: Optional[str] = None
    birth_date: Optional[date] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    line_id: Optional[str] = None
    notes: Optional[str] = None
    default_menu_id: Optional[int] = None
    default_duration: Optional[int] = None
    preferred_practitioner_id: Optional[int] = None

    @field_validator("last_name", "middle_name", "first_name", "full_name")
    @classmethod
    def normalize_name_fields(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = _normalize_name(v)
        return _validate_name_length(v) if v else None

    @field_validator("reading", "last_name_kana", "first_name_kana")
    @classmethod
    def normalize_reading(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = _normalize_name(v)
        return v or None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str | None) -> str | None:
        return _normalize_phone(v)

    @model_validator(mode="after")
    def validate_mode(self):
        if self.registration_mode == "split":
            if not self.last_name:
                raise ValueError("通常モードでは姓は必須です")
            if not self.first_name:
                raise ValueError("通常モードでは名は必須です")
        else:
            if not self.full_name:
                raise ValueError("フルネームモードではフルネームは必須です")
        return self


# ──────────────────────────────────────────────
# Update
# ──────────────────────────────────────────────
class PatientUpdate(BaseModel):
    registration_mode: Optional[Literal["split", "full_name"]] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    first_name: Optional[str] = None
    full_name: Optional[str] = None
    reading: Optional[str] = None
    last_name_kana: Optional[str] = None
    first_name_kana: Optional[str] = None
    birth_date: Optional[date] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    line_id: Optional[str] = None
    notes: Optional[str] = None
    default_menu_id: Optional[int] = None
    default_duration: Optional[int] = None
    preferred_practitioner_id: Optional[int] = None

    @field_validator("last_name", "middle_name", "first_name", "full_name")
    @classmethod
    def normalize_name_fields(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = _normalize_name(v)
        return _validate_name_length(v) if v else None

    @field_validator("reading", "last_name_kana", "first_name_kana")
    @classmethod
    def normalize_reading(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = _normalize_name(v)
        return v or None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str | None) -> str | None:
        return _normalize_phone(v)


# ──────────────────────────────────────────────
# Response
# ──────────────────────────────────────────────
class PatientResponse(BaseModel):
    id: int
    name: str
    registration_mode: str = "split"
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name_kana: Optional[str] = None
    first_name_kana: Optional[str] = None
    reading: Optional[str] = None
    birth_date: Optional[date] = None
    patient_number: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    line_id: Optional[str] = None
    notes: Optional[str] = None
    default_menu_id: Optional[int] = None
    default_duration: Optional[int] = None
    preferred_practitioner_id: Optional[int] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatientPageResponse(BaseModel):
    items: list[PatientResponse]
    total: int
    page: int
    per_page: int


# ──────────────────────────────────────────────
# Candidate
# ──────────────────────────────────────────────
class CandidateQuery(BaseModel):
    registration_mode: Literal["split", "full_name"] = "split"
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    full_name: Optional[str] = None
    reading: Optional[str] = None
    phone: Optional[str] = None
    birth_date: Optional[date] = None

    @field_validator("last_name", "first_name", "full_name", "reading")
    @classmethod
    def normalize_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _normalize_name(v) or None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str | None) -> str | None:
        return _normalize_phone(v)


class CandidateResponse(BaseModel):
    patient: PatientResponse
    match_reasons: list[str]


class PatientPurgeRequest(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("削除理由は2文字以上で入力してください")
        return v
