"""2段階認証API（スタッフPIN + 管理者ID/パスワード）"""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings as app_settings
from app.database import get_db
from app.models.setting import Setting
from app.utils.datetime_jst import now_jst

router = APIRouter(prefix="/api/auth", tags=["auth"])

# --- crypto ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"
STAFF_TOKEN_HOURS = 24
ADMIN_TOKEN_HOURS = 8


def _create_token(role: str, expires_delta: timedelta) -> str:
    expire = now_jst() + expires_delta
    payload = {"role": role, "exp": expire}
    return jwt.encode(payload, app_settings.secret_key, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, app_settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="トークンが無効または期限切れです")


# --- helpers ---
async def _get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def _set_setting(db: AsyncSession, key: str, value: str):
    result = await db.execute(select(Setting).where(Setting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    await db.flush()


# --- schemas ---
class StaffLoginRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=4)


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    token: str
    role: str


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=4)


# --- dependency functions (defined before endpoints that use them) ---
async def require_staff(authorization: Optional[str] = Header(None)) -> dict:
    """スタッフ以上の認証を要求"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="認証が必要です")
    payload = _decode_token(authorization[7:])
    if payload.get("role") not in ("staff", "admin"):
        raise HTTPException(status_code=403, detail="権限がありません")
    return payload


async def require_admin(authorization: Optional[str] = Header(None)) -> dict:
    """管理者認証を要求"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="管理者認証が必要です")
    payload = _decode_token(authorization[7:])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
    return payload


# backward compat
async def verify_token(authorization: Optional[str] = Header(None)):
    return await require_staff(authorization)


# --- endpoints ---
@router.post("/staff-login", response_model=TokenResponse)
async def staff_login(body: StaffLoginRequest, db: AsyncSession = Depends(get_db)):
    stored_pin = await _get_setting(db, "staff_pin")
    if stored_pin is None:
        stored_pin = "1234"
    if body.pin != stored_pin:
        raise HTTPException(status_code=401, detail="PINが正しくありません")
    token = _create_token("staff", timedelta(hours=STAFF_TOKEN_HOURS))
    return {"token": token, "role": "staff"}


@router.post("/admin-login", response_model=TokenResponse)
async def admin_login(body: AdminLoginRequest, db: AsyncSession = Depends(get_db)):
    stored_username = await _get_setting(db, "admin_username")
    stored_hash = await _get_setting(db, "admin_password_hash")
    if stored_username is None or stored_hash is None:
        raise HTTPException(status_code=500, detail="管理者アカウントが設定されていません")
    if body.username != stored_username:
        raise HTTPException(status_code=401, detail="IDまたはパスワードが正しくありません")
    if not pwd_context.verify(body.password, stored_hash):
        raise HTTPException(status_code=401, detail="IDまたはパスワードが正しくありません")
    token = _create_token("admin", timedelta(hours=ADMIN_TOKEN_HOURS))
    return {"token": token, "role": "admin"}


@router.post("/logout")
async def logout():
    return {"status": "ok"}


@router.get("/me")
async def me(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        return {"authenticated": False, "role": None}
    token = authorization[7:]
    try:
        payload = _decode_token(token)
        return {"authenticated": True, "role": payload.get("role")}
    except HTTPException:
        return {"authenticated": False, "role": None}


@router.put("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    _auth: dict = Depends(require_admin),
):
    hashed = pwd_context.hash(body.new_password)
    await _set_setting(db, "admin_password_hash", hashed)
    await db.commit()
    return {"status": "ok"}


@router.get("/verify")
async def verify(token: dict = Depends(require_staff)):
    return {"status": "authenticated", "role": token.get("role")}
