from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.menu import Menu

router = APIRouter(prefix="/api/public", tags=["public"])


class PublicMenuResponse(BaseModel):
    id: int
    name: str
    is_variable_time: bool
    base_minutes: int
    max_minutes: int


@router.get("/menus", response_model=list[PublicMenuResponse])
async def list_public_menus(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Menu)
        .where(Menu.is_active == True)
        .order_by(Menu.display_order, Menu.id)
    )
    menus = result.scalars().all()

    return [
        PublicMenuResponse(
            id=m.id,
            name=m.name,
            is_variable_time=bool(m.is_duration_variable),
            base_minutes=int(m.duration_minutes),
            max_minutes=int(m.max_duration_minutes or m.duration_minutes),
        )
        for m in menus
    ]
