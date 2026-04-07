from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.menu import Menu
from app.schemas.menu import MenuCreate, MenuUpdate, MenuResponse
from app.api.auth import require_admin

router = APIRouter(prefix="/api/menus", tags=["menus"])


@router.get("/", response_model=list[MenuResponse])
async def list_menus(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Menu).order_by(Menu.display_order, Menu.id)
    )
    return result.scalars().all()


@router.post("/", response_model=MenuResponse, status_code=201)
async def create_menu(data: MenuCreate, db: AsyncSession = Depends(get_db), _auth: dict = Depends(require_admin)):
    menu = Menu(**data.model_dump())
    db.add(menu)
    await db.commit()
    await db.refresh(menu)
    return menu


@router.put("/{menu_id}", response_model=MenuResponse)
async def update_menu(menu_id: int, data: MenuUpdate, db: AsyncSession = Depends(get_db), _auth: dict = Depends(require_admin)):
    result = await db.execute(select(Menu).where(Menu.id == menu_id))
    menu = result.scalar_one_or_none()
    if not menu:
        raise HTTPException(status_code=404, detail="メニューが見つかりません")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(menu, key, value)
    await db.commit()
    await db.refresh(menu)
    return menu


@router.delete("/{menu_id}", response_model=MenuResponse)
async def delete_menu(menu_id: int, db: AsyncSession = Depends(get_db), _auth: dict = Depends(require_admin)):
    """論理削除（is_active=False）"""
    result = await db.execute(select(Menu).where(Menu.id == menu_id))
    menu = result.scalar_one_or_none()
    if not menu:
        raise HTTPException(status_code=404, detail="メニューが見つかりません")
    menu.is_active = False
    await db.commit()
    await db.refresh(menu)
    return menu
