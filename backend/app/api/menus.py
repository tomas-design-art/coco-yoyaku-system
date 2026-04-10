from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete as sa_delete

from app.database import get_db
from app.models.menu import Menu, MenuPriceTier
from app.models.patient import Patient
from app.models.reservation import Reservation
from app.schemas.menu import MenuCreate, MenuUpdate, MenuResponse
from app.api.auth import require_admin

router = APIRouter(prefix="/api/menus", tags=["menus"])


@router.get("/", response_model=list[MenuResponse])
async def list_menus(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Menu).order_by(Menu.display_order, Menu.id)
    )
    return result.scalars().unique().all()


@router.post("/", response_model=MenuResponse, status_code=201)
async def create_menu(data: MenuCreate, db: AsyncSession = Depends(get_db), _auth: dict = Depends(require_admin)):
    tier_data = data.price_tiers
    menu_dict = data.model_dump(exclude={"price_tiers"})
    menu = Menu(**menu_dict)
    for i, t in enumerate(tier_data):
        menu.price_tiers.append(MenuPriceTier(
            duration_minutes=t.duration_minutes,
            price=t.price,
            display_order=t.display_order if t.display_order else i,
        ))
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
    tiers_input = update_data.pop("price_tiers", None)
    for key, value in update_data.items():
        setattr(menu, key, value)
    if tiers_input is not None:
        # Replace all tiers
        await db.execute(sa_delete(MenuPriceTier).where(MenuPriceTier.menu_id == menu_id))
        for i, t in enumerate(tiers_input):
            db.add(MenuPriceTier(
                menu_id=menu_id,
                duration_minutes=t["duration_minutes"],
                price=t.get("price"),
                display_order=t.get("display_order", i),
            ))
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


@router.post("/{menu_id}/purge")
async def purge_menu(menu_id: int, db: AsyncSession = Depends(get_db), _auth: dict = Depends(require_admin)):
    """完全削除（2段階目）: 先に論理削除済みのメニューのみ削除可能。"""
    result = await db.execute(select(Menu).where(Menu.id == menu_id))
    menu = result.scalar_one_or_none()
    if not menu:
        raise HTTPException(status_code=404, detail="メニューが見つかりません")
    if menu.is_active:
        raise HTTPException(status_code=400, detail="先にメニューを無効化してください")

    # 参照を切ってから削除（過去予約・患者デフォルト設定の整合性維持）
    await db.execute(
        update(Reservation)
        .where(Reservation.menu_id == menu_id)
        .values(menu_id=None)
    )
    await db.execute(
        update(Patient)
        .where(Patient.default_menu_id == menu_id)
        .values(default_menu_id=None)
    )

    await db.delete(menu)
    await db.commit()
    return {"status": "ok", "deleted_id": menu_id}
