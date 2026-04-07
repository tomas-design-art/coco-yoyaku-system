"""番号なし患者に一括で患者番号を採番するスクリプト"""
import asyncio
from sqlalchemy import text
from app.database import async_session


async def fix():
    async with async_session() as db:
        rows = (await db.execute(text(
            "SELECT id, name, patient_number, line_id FROM patients "
            "WHERE patient_number IS NULL OR patient_number = ''"
        ))).fetchall()
        print(f"番号なし患者: {len(rows)}件")
        for r in rows:
            print(f"  id={r[0]} name={r[1]} number={r[2]} line_id={r[3]}")
        if not rows:
            print("対象なし")
            return
        max_row = (await db.execute(text(
            "SELECT MAX(patient_number) FROM patients WHERE patient_number ~ '^P[0-9]+$'"
        ))).scalar()
        next_val = int(max_row[1:]) + 1 if max_row else 1
        for r in rows:
            pnum = f"P{next_val:06d}"
            await db.execute(
                text("UPDATE patients SET patient_number = :pn WHERE id = :id"),
                {"pn": pnum, "id": r[0]},
            )
            print(f"  -> id={r[0]} {r[1]} => {pnum}")
            next_val += 1
        await db.commit()
        print("完了")


if __name__ == "__main__":
    asyncio.run(fix())
