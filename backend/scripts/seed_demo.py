"""デモデータ投入スクリプト
施術者3名・メニュー10種・予約色3色・患者10名・今週の予約 30件を挿入。
冪等に実行可能: source_ref='DEMO-XXX' が既に存在する場合はスキップ。

■ 営業スケジュール（DBの実設定に準拠）
  day_of_week 0=日 09:00-19:00  ←→ this_monday()+6
  day_of_week 1=月 10:00-21:00  ←→ this_monday()+0
  day_of_week 2=火 定休日        ←→ this_monday()+1  ★予約なし
  day_of_week 3=水 10:00-21:00  ←→ this_monday()+2
  day_of_week 4=木 10:00-21:00  ←→ this_monday()+3
  day_of_week 5=金 10:00-21:00  ←→ this_monday()+4
  day_of_week 6=土 09:00-19:00  ←→ this_monday()+5
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import zoneinfo
from sqlalchemy import select

from app.database import async_session
from app.models.practitioner import Practitioner
from app.models.patient import Patient
from app.models.menu import Menu
from app.models.reservation_color import ReservationColor
from app.models.reservation import Reservation

JST = zoneinfo.ZoneInfo("Asia/Tokyo")

# ---------------------------------------------------------------------------
# マスターデータ定義（現在DBにある確定データを正式デモデータとして定義）
# ---------------------------------------------------------------------------
PRACTITIONERS = [
    {"name": "田中 太郎", "role": "院長",   "display_order": 1},
    {"name": "鈴木 花子", "role": "施術者", "display_order": 2},
    {"name": "佐藤 健二", "role": "施術者", "display_order": 3},
]

# color_id は予約色の name で解決するため別途マッピング
MENUS = [
    # name, duration_minutes, price, is_duration_variable, max_duration_minutes, color_name, display_order
    ("保険診療３割負担", 15,   900, True,  45,   "保険診療",               0),
    ("深層筋",           30,  4000, True,  90,   "自費診療",               1),
    ("マッスルセラピー", 15,  1700, True,  95,   "自費診療",               2),
    ("妊婦ケア",         45,  5000, False, None, "自費診療",               3),
    ("整体調整",         60,  6000, False, None, "初診／ホットペッパー予約", 4),
    ("骨盤矯正",         45,  5000, False, None, "自費診療",               5),
    ("肩こり解消",       30,  3500, False, None, "自費診療",               6),
    ("腰痛治療",         45,  4500, False, None, "保険診療",               7),
    ("全身整体",         90,  9000, False, None, "初診／ホットペッパー予約", 8),
    ("初診カウンセリング", 30, 0,   False, None, "保険診療",               9),
]

# 予約色：初回マイグレーション（002）で挿入されるデフォルト3色を確認・補完するのみ
COLORS = [
    {"name": "保険診療",               "color_code": "#3B82F6", "display_order": 1, "is_default": True},
    {"name": "自費診療",               "color_code": "#10B981", "display_order": 2, "is_default": False},
    {"name": "初診／ホットペッパー予約", "color_code": "#F97316", "display_order": 3, "is_default": False},
]

PATIENTS = [
    {"name": "山田 一郎",   "last_name": "山田",  "first_name": "一郎",   "last_name_kana": "ヤマダ",   "first_name_kana": "イチロウ", "patient_number": "P000001"},
    {"name": "田中 美咲",   "last_name": "田中",  "first_name": "美咲",   "last_name_kana": "タナカ",   "first_name_kana": "ミサキ",   "patient_number": "P000002"},
    {"name": "中村 健太",   "last_name": "中村",  "first_name": "健太",   "last_name_kana": "ナカムラ", "first_name_kana": "ケンタ",   "patient_number": "P000003"},
    {"name": "佐藤 陽子",   "last_name": "佐藤",  "first_name": "陽子",   "last_name_kana": "サトウ",   "first_name_kana": "ヨウコ",   "patient_number": "P000004"},
    {"name": "小林 浩二",   "last_name": "小林",  "first_name": "浩二",   "last_name_kana": "コバヤシ", "first_name_kana": "コウジ",   "patient_number": "P000005"},
    {"name": "伊藤 さくら", "last_name": "伊藤",  "first_name": "さくら", "last_name_kana": "イトウ",   "first_name_kana": "サクラ",   "patient_number": "P000006"},
    {"name": "渡辺 誠",     "last_name": "渡辺",  "first_name": "誠",     "last_name_kana": "ワタナベ", "first_name_kana": "マコト",   "patient_number": "P000007"},
    {"name": "木村 愛",     "last_name": "木村",  "first_name": "愛",     "last_name_kana": "キムラ",   "first_name_kana": "アイ",     "patient_number": "P000008"},
    {"name": "林 大輔",     "last_name": "林",    "first_name": "大輔",   "last_name_kana": "ハヤシ",   "first_name_kana": "ダイスケ", "patient_number": "P000009"},
    {"name": "清水 恵子",   "last_name": "清水",  "first_name": "恵子",   "last_name_kana": "シミズ",   "first_name_kana": "ケイコ",   "patient_number": "P000010"},
]


def this_monday() -> datetime:
    """今週の月曜日 JST 00:00 を返す"""
    now = datetime.now(JST)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())


def dt(monday: datetime, day_offset: int, hour: int, minute: int) -> datetime:
    return monday + timedelta(days=day_offset, hours=hour, minutes=minute)


# ---------------------------------------------------------------------------
# 予約データ定義 (30件)
#
# ■ 曜日とoffsetの対応
#   +0=月(10-21)  +1=火(定休★) +2=水(10-21)
#   +3=木(10-21)  +4=金(10-21) +5=土(09-19)  +6=日(09-19)
#
# ■ 予約ルール
#   ・全予約の start_time / end_time が各日の営業時間内に収まること
#   ・CONFIRMED / PENDING / HOLD は同一施術者の同時刻重複なし
#   ・CANCEL_REQUESTED / CHANGE_REQUESTED は制約対象外
#   ・p=施術者idx(0-2), pt=患者idx(0-9), m=メニューidx(0-9)
#
# ■ メニューidx → (name, 所要分)
#   0: 保険診療３割負担(15), 1: 深層筋(30),        2: マッスルセラピー(15)
#   3: 妊婦ケア(45),         4: 整体調整(60),       5: 骨盤矯正(45)
#   6: 肩こり解消(30),       7: 腰痛治療(45),       8: 全身整体(90)
#   9: 初診カウンセリング(30)
# ---------------------------------------------------------------------------
def build_reservations(monday: datetime) -> list[dict]:
    now = datetime.now(JST)
    return [
        # ══ 月曜 offset=0  営業 10:00-21:00 ════════════════════════════════
        {"ref": "DEMO-001", "p": 0, "pt": 0, "m": 4,           # 整体調整60分
         "s": dt(monday, 0, 10,  0), "e": dt(monday, 0, 11,  0),
         "status": "CONFIRMED",        "channel": "PHONE"},
        {"ref": "DEMO-002", "p": 0, "pt": 1, "m": 6,           # 肩こり解消30分
         "s": dt(monday, 0, 11, 30), "e": dt(monday, 0, 12,  0),
         "status": "CONFIRMED",        "channel": "LINE"},
        {"ref": "DEMO-003", "p": 1, "pt": 2, "m": 5,           # 骨盤矯正45分
         "s": dt(monday, 0, 10,  0), "e": dt(monday, 0, 10, 45),
         "status": "PENDING",          "channel": "CHATBOT"},
        {"ref": "DEMO-004", "p": 1, "pt": 3, "m": 7,           # 腰痛治療45分 CANCEL_REQUESTED
         "s": dt(monday, 0, 14,  0), "e": dt(monday, 0, 14, 45),
         "status": "CANCEL_REQUESTED", "channel": "PHONE"},
        {"ref": "DEMO-005", "p": 2, "pt": 4, "m": 9,           # 初診カウンセリング30分
         "s": dt(monday, 0, 10,  0), "e": dt(monday, 0, 10, 30),
         "status": "CONFIRMED",        "channel": "WALK_IN"},

        # ══ 火曜 offset=1  定休日 ★予約なし ════════════════════════════════

        # ══ 水曜 offset=2  営業 10:00-21:00 ════════════════════════════════
        {"ref": "DEMO-006", "p": 0, "pt": 5, "m": 0,           # 保険診療15分 HotPepper同期済
         "s": dt(monday, 2, 10,  0), "e": dt(monday, 2, 10, 15),
         "status": "CONFIRMED",        "channel": "HOTPEPPER",
         "hotpepper_synced": True},
        {"ref": "DEMO-007", "p": 0, "pt": 6, "m": 2,           # マッスルセラピー15分 HotPepper未同期+conflict
         "s": dt(monday, 2, 14,  0), "e": dt(monday, 2, 14, 15),
         "status": "CONFIRMED",        "channel": "HOTPEPPER",
         "hotpepper_synced": False,
         "conflict_note": "HotPepper登録時に10:00-10:15枠と重複検出"},
        {"ref": "DEMO-008", "p": 1, "pt": 7, "m": 8,           # 全身整体90分 HOLD(2時間後期限)
         "s": dt(monday, 2, 10,  0), "e": dt(monday, 2, 11, 30),
         "status": "HOLD",             "channel": "CHATBOT",
         "hold_expires_at": now + timedelta(hours=2)},
        {"ref": "DEMO-009", "p": 2, "pt": 8, "m": 4,           # 整体調整60分
         "s": dt(monday, 2, 10,  0), "e": dt(monday, 2, 11,  0),
         "status": "CONFIRMED",        "channel": "LINE"},
        {"ref": "DEMO-010", "p": 2, "pt": 9, "m": 5,           # 骨盤矯正45分
         "s": dt(monday, 2, 13,  0), "e": dt(monday, 2, 13, 45),
         "status": "CONFIRMED",        "channel": "PHONE"},

        # ══ 木曜 offset=3  営業 10:00-21:00 ════════════════════════════════
        {"ref": "DEMO-011", "p": 0, "pt": 0, "m": 1,           # 深層筋30分
         "s": dt(monday, 3, 10,  0), "e": dt(monday, 3, 10, 30),
         "status": "CONFIRMED",        "channel": "PHONE"},
        {"ref": "DEMO-012", "p": 0, "pt": 1, "m": 4,           # 整体調整60分 PENDING
         "s": dt(monday, 3, 13,  0), "e": dt(monday, 3, 14,  0),
         "status": "PENDING",          "channel": "LINE"},
        {"ref": "DEMO-013", "p": 1, "pt": 2, "m": 7,           # 腰痛治療45分
         "s": dt(monday, 3, 10,  0), "e": dt(monday, 3, 10, 45),
         "status": "CONFIRMED",        "channel": "WALK_IN"},
        {"ref": "DEMO-014", "p": 1, "pt": 3, "m": 6,           # 肩こり解消30分 CANCEL_REQUESTED
         "s": dt(monday, 3, 15,  0), "e": dt(monday, 3, 15, 30),
         "status": "CANCEL_REQUESTED", "channel": "PHONE"},
        {"ref": "DEMO-015", "p": 2, "pt": 4, "m": 8,           # 全身整体90分 HotPepper同期済
         "s": dt(monday, 3, 10,  0), "e": dt(monday, 3, 11, 30),
         "status": "CONFIRMED",        "channel": "HOTPEPPER",
         "hotpepper_synced": True},

        # ══ 金曜 offset=4  営業 10:00-21:00 ════════════════════════════════
        {"ref": "DEMO-016", "p": 0, "pt": 5, "m": 4,           # 整体調整60分
         "s": dt(monday, 4, 10,  0), "e": dt(monday, 4, 11,  0),
         "status": "CONFIRMED",        "channel": "LINE"},
        {"ref": "DEMO-017", "p": 0, "pt": 6, "m": 6,           # 肩こり解消30分
         "s": dt(monday, 4, 14,  0), "e": dt(monday, 4, 14, 30),
         "status": "CONFIRMED",        "channel": "PHONE"},
        {"ref": "DEMO-018", "p": 1, "pt": 7, "m": 7,           # 腰痛治療45分 PENDING
         "s": dt(monday, 4, 10,  0), "e": dt(monday, 4, 10, 45),
         "status": "PENDING",          "channel": "CHATBOT"},
        {"ref": "DEMO-019", "p": 1, "pt": 8, "m": 5,           # 骨盤矯正45分 CHANGE_REQUESTED
         "s": dt(monday, 4, 16,  0), "e": dt(monday, 4, 16, 45),
         "status": "CHANGE_REQUESTED", "channel": "LINE"},
        {"ref": "DEMO-020", "p": 2, "pt": 9, "m": 9,           # 初診カウンセリング30分
         "s": dt(monday, 4, 10,  0), "e": dt(monday, 4, 10, 30),
         "status": "CONFIRMED",        "channel": "WALK_IN"},

        # ══ 土曜 offset=5  営業 09:00-19:00 ════════════════════════════════
        {"ref": "DEMO-021", "p": 0, "pt": 0, "m": 4,           # 整体調整60分
         "s": dt(monday, 5,  9,  0), "e": dt(monday, 5, 10,  0),
         "status": "CONFIRMED",        "channel": "PHONE"},
        {"ref": "DEMO-022", "p": 0, "pt": 1, "m": 3,           # 妊婦ケア45分
         "s": dt(monday, 5, 15,  0), "e": dt(monday, 5, 15, 45),
         "status": "CONFIRMED",        "channel": "LINE"},
        {"ref": "DEMO-023", "p": 1, "pt": 2, "m": 1,           # 深層筋30分 PENDING
         "s": dt(monday, 5,  9,  0), "e": dt(monday, 5,  9, 30),
         "status": "PENDING",          "channel": "CHATBOT"},
        {"ref": "DEMO-024", "p": 1, "pt": 3, "m": 8,           # 全身整体90分 HOLD(2時間後期限)
         "s": dt(monday, 5, 13,  0), "e": dt(monday, 5, 14, 30),
         "status": "HOLD",             "channel": "LINE",
         "hold_expires_at": now + timedelta(hours=2)},
        {"ref": "DEMO-025", "p": 2, "pt": 4, "m": 6,           # 肩こり解消30分
         "s": dt(monday, 5,  9,  0), "e": dt(monday, 5,  9, 30),
         "status": "CONFIRMED",        "channel": "WALK_IN"},

        # ══ 日曜 offset=6  営業 09:00-19:00 ════════════════════════════════
        {"ref": "DEMO-026", "p": 0, "pt": 5, "m": 5,           # 骨盤矯正45分
         "s": dt(monday, 6,  9,  0), "e": dt(monday, 6,  9, 45),
         "status": "CONFIRMED",        "channel": "PHONE"},
        {"ref": "DEMO-027", "p": 0, "pt": 6, "m": 0,           # 保険診療15分
         "s": dt(monday, 6, 14,  0), "e": dt(monday, 6, 14, 15),
         "status": "CONFIRMED",        "channel": "HOTPEPPER",
         "hotpepper_synced": True},
        {"ref": "DEMO-028", "p": 1, "pt": 7, "m": 2,           # マッスルセラピー15分 PENDING
         "s": dt(monday, 6,  9,  0), "e": dt(monday, 6,  9, 15),
         "status": "PENDING",          "channel": "LINE"},
        {"ref": "DEMO-029", "p": 2, "pt": 8, "m": 7,           # 腰痛治療45分
         "s": dt(monday, 6,  9,  0), "e": dt(monday, 6,  9, 45),
         "status": "CONFIRMED",        "channel": "PHONE"},
        {"ref": "DEMO-030", "p": 2, "pt": 9, "m": 9,           # 初診カウンセリング30分 CHANGE_REQUESTED
         "s": dt(monday, 6, 16,  0), "e": dt(monday, 6, 16, 30),
         "status": "CHANGE_REQUESTED", "channel": "CHATBOT"},
    ]


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------
async def get_or_create_practitioner(db, d: dict) -> Practitioner:
    r = await db.execute(select(Practitioner).where(Practitioner.name == d["name"]))
    obj = r.scalar_one_or_none()
    if obj:
        print(f"  Exists: Practitioner '{d['name']}'")
        return obj
    obj = Practitioner(**d, is_active=True)
    db.add(obj)
    await db.flush()
    print(f"  Added:  Practitioner '{d['name']}'")
    return obj


async def get_or_create_color(db, d: dict) -> ReservationColor:
    r = await db.execute(select(ReservationColor).where(ReservationColor.name == d["name"]))
    obj = r.scalar_one_or_none()
    if obj:
        # is_default / color_code が変わっていれば更新
        updated = False
        for key in ("color_code", "display_order", "is_default"):
            if getattr(obj, key) != d[key]:
                setattr(obj, key, d[key])
                updated = True
        if updated:
            await db.flush()
            print(f"  Updated: Color '{d['name']}'")
        else:
            print(f"  Exists: Color '{d['name']}'")
        return obj
    obj = ReservationColor(**d)
    db.add(obj)
    await db.flush()
    print(f"  Added:  Color '{d['name']}'")
    return obj


async def upsert_menu(db, row: tuple, color_map: dict[str, int]) -> Menu:
    name, duration, price, is_variable, max_dur, color_name, order = row
    color_id = color_map.get(color_name)
    r = await db.execute(select(Menu).where(Menu.name == name))
    obj = r.scalar_one_or_none()
    if obj:
        # フィールドを常に最新値に更新（デモデータが正とする）
        obj.duration_minutes      = duration
        obj.price                 = price
        obj.is_duration_variable  = is_variable
        obj.max_duration_minutes  = max_dur
        obj.color_id              = color_id
        obj.display_order         = order
        obj.is_active             = True
        await db.flush()
        print(f"  Upserted: Menu '{name}'")
        return obj
    obj = Menu(
        name=name, duration_minutes=duration, price=price,
        is_duration_variable=is_variable, max_duration_minutes=max_dur,
        color_id=color_id, display_order=order, is_active=True,
    )
    db.add(obj)
    await db.flush()
    print(f"  Added:  Menu '{name}'")
    return obj


async def get_or_create_patient(db, d: dict) -> Patient:
    r = await db.execute(select(Patient).where(Patient.name == d["name"]))
    obj = r.scalar_one_or_none()
    if obj:
        updated = False
        for key in ("last_name", "first_name", "last_name_kana", "first_name_kana"):
            if key in d and getattr(obj, key, None) != d[key]:
                setattr(obj, key, d[key])
                updated = True
        if "patient_number" in d and not obj.patient_number:
            obj.patient_number = d["patient_number"]
            updated = True
        if updated:
            await db.flush()
            print(f"  Updated: Patient '{d['name']}'")
        else:
            print(f"  Exists: Patient '{d['name']}'")
        return obj
    obj = Patient(**d)
    db.add(obj)
    await db.flush()
    print(f"  Added:  Patient '{d['name']}'")
    return obj


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
async def seed_demo():
    async with async_session() as db:
        print("\n=== 施術者 ===")
        practitioners = [await get_or_create_practitioner(db, d) for d in PRACTITIONERS]

        print("\n=== 予約色 ===")
        color_objs = [await get_or_create_color(db, d) for d in COLORS]
        await db.flush()
        color_map = {c.name: c.id for c in color_objs}

        print("\n=== メニュー ===")
        menus = [await upsert_menu(db, row, color_map) for row in MENUS]

        print("\n=== 患者 ===")
        patients = [await get_or_create_patient(db, d) for d in PATIENTS]

        await db.commit()

        print("\n=== 予約 (今週30件 ／ 火曜定休のため月・水〜日) ===")
        monday = this_monday()
        print(f"  今週月曜: {monday.strftime('%Y-%m-%d')}")

        rdata = build_reservations(monday)
        added = 0
        skipped = 0
        for rd in rdata:
            r = await db.execute(
                select(Reservation).where(Reservation.source_ref == rd["ref"])
            )
            if r.scalar_one_or_none():
                print(f"  Exists: {rd['ref']}")
                skipped += 1
                continue

            reservation = Reservation(
                patient_id=patients[rd["pt"]].id,
                practitioner_id=practitioners[rd["p"]].id,
                menu_id=menus[rd["m"]].id,
                start_time=rd["s"],
                end_time=rd["e"],
                status=rd["status"],
                channel=rd["channel"],
                source_ref=rd["ref"],
                hotpepper_synced=rd.get("hotpepper_synced", False),
                conflict_note=rd.get("conflict_note"),
                hold_expires_at=rd.get("hold_expires_at"),
            )
            db.add(reservation)
            try:
                await db.flush()
                print(f"  Added:  {rd['ref']} [{rd['status']}] {rd['s'].strftime('%m/%d(%a) %H:%M')}-{rd['e'].strftime('%H:%M')} {rd['channel']}")
                added += 1
            except Exception as exc:
                await db.rollback()
                print(f"  ERROR:  {rd['ref']} — {exc}")

        await db.commit()

    print(f"\nDone. Added={added}, Skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(seed_demo())
