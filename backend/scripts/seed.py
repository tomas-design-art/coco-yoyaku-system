"""初期データ投入スクリプト"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from passlib.context import CryptContext
from sqlalchemy import select
from app.database import async_session
from app.models.setting import Setting

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

INITIAL_SETTINGS = [
    ("hold_duration_minutes", "10"),
    ("hotpepper_priority", "true"),
    ("business_hour_start", "09:00"),
    ("business_hour_end", "20:00"),
    ("business_days", "1,2,3,4,5,6"),
    ("slot_interval_minutes", "5"),
    ("notification_sound", "true"),
    # チャットボット設定
    ("chatbot_enabled", "true"),
    ("chatbot_accept_start", "00:00"),
    ("chatbot_accept_end", "23:59"),
    ("chatbot_greeting", "こんにちは！ご予約のお手伝いをいたします。\nご希望の日時やメニューをお聞かせください。"),
    ("chatbot_confirm_message", "当日のご来院をお待ちしております。\nご変更・キャンセルはお電話にてお願いいたします。"),
    ("chatbot_system_prompt", "あなたは予約受付アシスタントです。\n患者さんと丁寧に会話しながら、予約を受け付けてください。\n\nルール:\n1. 予約に必要な情報を会話で収集する:\n   - 希望日時\n   - 施術メニュー（メニュー一覧から選択）\n   - 患者名\n   - 電話番号\n2. 情報が揃ったら空き状況を確認する\n3. 空いていれば予約を確定する\n4. 空いていなければ代替候補を最大3つ提案する\n5. 敬語で丁寧に対応する\n6. 予約に関係ない質問には「お電話でお問い合わせください」と案内する"),
    ("chatbot_disabled_message", "申し訳ございません。現在チャットボット機能は準備中です。お電話にてお問い合わせください。"),
    # LINE自動返信
    ("line_reply_reservation", "ご予約のご連絡ありがとうございます。\nご希望の日時を確認し、折り返しご連絡いたします。"),
    ("line_reply_default", "メッセージを受け付けました。内容を確認いたします。"),
    # 施術者ロール選択肢（カンマ区切り）
    ("practitioner_roles", "院長,施術者"),
    # 祝日営業設定
    ("holiday_mode", "closed"),
    ("holiday_start_time", "09:00"),
    ("holiday_end_time", "13:00"),
    # 認証設定
    ("staff_pin", "1234"),
    ("admin_username", "admin"),
    ("admin_password_hash", pwd_context.hash("admin")),
]


async def seed():
    async with async_session() as db:
        for key, value in INITIAL_SETTINGS:
            result = await db.execute(select(Setting).where(Setting.key == key))
            existing = result.scalar_one_or_none()
            if not existing:
                db.add(Setting(key=key, value=value))
                print(f"  Added: {key} = {value}")
            else:
                print(f"  Exists: {key} = {existing.value}")
        await db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
