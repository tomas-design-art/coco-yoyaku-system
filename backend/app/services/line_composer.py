"""LINE autopilot 向けの安全な返信文生成。"""
from __future__ import annotations

import json


def _fallback(situation: str, context: dict) -> str:
    templates = {
        "ask_datetime": "ご希望の日時を教えてください。\n例: 明日の午後3時",
        "confirm_slot": "こちらの日時でよろしいでしょうか？\nはい / いいえ",
        "confirmed": "ご予約を確定しました。ご来院をお待ちしております。",
        "offer_alternatives": "ご希望に近い空き枠をご案内します。番号でお知らせください。",
        "parse_failed": "うまく聞き取れず申し訳ありません。ご希望の日にちと時間帯をもう一度教えていただけますか？\n例: 明日の午後3時ごろ",
        "handoff_to_human": "内容を確認のうえ担当者からご案内します。少々お待ちください。",
        "cancel_done": "ご予約をキャンセルしました。",
        "change_done": "ご予約を変更しました。ご来院をお待ちしております。",
    }
    return templates.get(situation, "内容を確認いたします。")


async def compose_reply(situation: str, context: dict) -> str:
    """与えられた事実だけで短文を生成し、失敗時は必ず定型文を返す。"""
    fallback = _fallback(situation, context)
    try:
        from app.config import settings
        if not settings.gemini_api_key:
            return fallback
        import httpx

        prompt = (
            "あなたは接骨院の受付ベテラン事務員です。以下の確定事実だけを使い、患者への短い返信を作ってください。"
            "事実にない日時・空き・診療内容を作らず、数値・固有名は改変しない。敬語で1〜3文、絵文字は最大1つ。"
            "医療的な指示や診断はしない。返信文だけを返す。\n"
            f"状況: {situation}\n確定事実(JSON): {json.dumps(context, ensure_ascii=False)}"
        )
        response = await httpx.AsyncClient().post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
            headers={"x-goog-api-key": settings.gemini_api_key},
            json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 160}},
            timeout=10,
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text if text else fallback
    except Exception:
        return fallback