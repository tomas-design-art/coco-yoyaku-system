"""初期データ投入スクリプト"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.services.bootstrap import seed_initial_settings


async def seed():
    async with async_session() as db:
        await seed_initial_settings(db)
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
