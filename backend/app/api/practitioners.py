from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update as sa_update

from app.database import get_db
from app.models.practitioner import Practitioner
from app.schemas.practitioner import PractitionerCreate, PractitionerUpdate, PractitionerResponse
from app.api.auth import require_admin

router = APIRouter(prefix="/api/practitioners", tags=["practitioners"])


@router.get("/", response_model=list[PractitionerResponse])
async def list_practitioners(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Practitioner).order_by(Practitioner.display_order, Practitioner.id)
    )
    return result.scalars().all()


@router.post("/", response_model=PractitionerResponse, status_code=201)
async def create_practitioner(data: PractitionerCreate, db: AsyncSession = Depends(get_db), _auth: dict = Depends(require_admin)):
    practitioner = Practitioner(**data.model_dump())
    db.add(practitioner)
    await db.commit()
    await db.refresh(practitioner)
    return practitioner


@router.put("/{practitioner_id}", response_model=PractitionerResponse)
async def update_practitioner(
    practitioner_id: int, data: PractitionerUpdate, db: AsyncSession = Depends(get_db), _auth: dict = Depends(require_admin)
):
    result = await db.execute(select(Practitioner).where(Practitioner.id == practitioner_id))
    practitioner = result.scalar_one_or_none()
    if not practitioner:
        raise HTTPException(status_code=404, detail="施術者が見つかりません")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(practitioner, key, value)
    await db.commit()
    await db.refresh(practitioner)
    return practitioner


@router.delete("/{practitioner_id}", response_model=PractitionerResponse)
async def delete_practitioner(practitioner_id: int, db: AsyncSession = Depends(get_db), _auth: dict = Depends(require_admin)):
    """論理削除（is_active=False）"""
    result = await db.execute(select(Practitioner).where(Practitioner.id == practitioner_id))
    practitioner = result.scalar_one_or_none()
    if not practitioner:
        raise HTTPException(status_code=404, detail="施術者が見つかりません")
    practitioner.is_active = False
    await db.commit()
    await db.refresh(practitioner)
    return practitioner
