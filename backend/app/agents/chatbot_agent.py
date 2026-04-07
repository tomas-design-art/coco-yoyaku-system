"""チャットボットAIエージェント — Tool定義 + LLM呼び出し"""
import json
import logging
from datetime import date, time, datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# DB (settings テーブル) の chatbot_system_prompt が優先。
# DB 未設定 or 取得失敗時のフォールバック値。
DEFAULT_SYSTEM_PROMPT = """
あなたは整骨院の、温かく丁寧な受付スタッフです。
患者さんの不安をやわらげる自然な会話で、予約受付を進めてください。

会話トーン:
- 機械的な言い方（例: 「入力してください」）は避ける。
- 「〜ですね」「〜でしょうか？」など、人に話しかける自然な敬語を使う。
- 1回の返信はLINEで読みやすい短文にまとめる（目安3〜4行）。
- 箇条書きの多用を避け、必要最小限にする。

進行ルール:
1. 予約に必要な情報を会話で収集する:
    - 希望日時
    - 施術メニュー（メニュー一覧から選択）
    - 患者名
    - 電話番号
2. 情報が揃ったら空き状況を確認する。
3. 空いていれば予約を確定する。
4. 空いていなければ代替候補を最大3つ提案する。
5. 予約に関係ない質問には「お電話でお問い合わせください」と案内する。

リピーター対応:
- もし system context に `repeat_customer=true` が含まれる場合、冒頭に自然な感謝を添える。
- 例: 「いつもご来院ありがとうございます。」
- さらに `last_menu_name` や `last_duration_minutes` があれば、押し付けずに確認として活用する。

利用可能なツール:
- get_available_menus: 施術メニュー一覧を取得
- check_availability: 指定日時に予約可能か確認
- suggest_alternatives: 代替候補を最大3件提案
- create_reservation: 予約を確定

必要な情報がすべて揃うまで、一つずつ確認してください。
患者さんが曖昧な希望を出した場合は、具体的に聞き返してください。
"""

# 後方互換: 既存コードが CHATBOT_SYSTEM_PROMPT を参照している箇所のため残す
CHATBOT_SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT

TOOL_DEFINITIONS = [
    {
        "name": "get_available_menus",
        "description": "施術メニュー一覧を取得する",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "check_availability",
        "description": "指定日時に予約可能か確認する",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "start_time": {"type": "string", "description": "HH:MM"},
                "duration_minutes": {"type": "integer", "description": "施術時間（分）"},
            },
            "required": ["date", "start_time", "duration_minutes"],
        },
    },
    {
        "name": "suggest_alternatives",
        "description": "指定日時が空いていない場合、近い日時の空き枠を最大3件提案する",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "preferred_time": {"type": "string", "description": "HH:MM"},
                "duration_minutes": {"type": "integer", "description": "施術時間（分）"},
                "search_days": {"type": "integer", "description": "前後何日まで探すか（デフォルト3）"},
            },
            "required": ["date", "preferred_time", "duration_minutes"],
        },
    },
    {
        "name": "create_reservation",
        "description": "予約を確定する",
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "患者名"},
                "phone": {"type": "string", "description": "電話番号"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "start_time": {"type": "string", "description": "HH:MM"},
                "menu_id": {"type": "integer", "description": "メニューID"},
                "duration_minutes": {"type": "integer", "description": "施術時間（分）"},
            },
            "required": ["patient_name", "phone", "date", "start_time", "menu_id", "duration_minutes"],
        },
    },
]


async def execute_tool(
    tool_name: str,
    tool_args: dict,
    db: AsyncSession,
) -> dict:
    """ツールを実行して結果を返す"""
    from app.services.chatbot_service import (
        tool_get_menus,
        tool_check_availability,
        tool_suggest_alternatives,
        tool_create_reservation,
    )

    if tool_name == "get_available_menus":
        return await tool_get_menus(db)
    elif tool_name == "check_availability":
        return await tool_check_availability(
            db,
            tool_args["date"],
            tool_args["start_time"],
            tool_args["duration_minutes"],
        )
    elif tool_name == "suggest_alternatives":
        return await tool_suggest_alternatives(
            db,
            tool_args["date"],
            tool_args["preferred_time"],
            tool_args["duration_minutes"],
            tool_args.get("search_days", 3),
        )
    elif tool_name == "create_reservation":
        return await tool_create_reservation(
            db,
            tool_args["patient_name"],
            tool_args["phone"],
            tool_args["date"],
            tool_args["start_time"],
            tool_args["menu_id"],
            tool_args["duration_minutes"],
        )
    else:
        return {"error": f"Unknown tool: {tool_name}"}
