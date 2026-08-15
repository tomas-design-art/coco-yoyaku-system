"""LINE autopilot 向けの安全な返信文生成。"""
from __future__ import annotations

import json
import logging


logger = logging.getLogger(__name__)

SITUATION_GUIDES = {
    "confirm_slot": "提示した日時・担当・メニューを省略せず、この内容で良いか確認する。はい/いいえで答えられると伝える。",
    "offer_alternatives": "候補を番号付きで見やすく並べ、希望する番号で選べると伝える。候補が空なら別の希望日時を尋ねる。",
    "usual_confirm": "いつものメニュー・所要時間・担当を提示し、この内容で良いか確認する。",
    "ask_datetime": "症状があれば一言いたわった上で、希望日時を尋ねる。",
    "ask_missing": "不足項目だけを責めずに尋ねる。複数ある場合も確定事実の項目名を使う。",
    "ask_menu": "予約に必要なメニュー選択を簡潔に促す。",
    "confirmed": "予約が確定したことと、確定した日時・担当・メニューを伝えて来院を歓迎する。",
    "cancel_done": "指定された予約のキャンセル完了を事実だけで伝える。",
    "change_done": "予約変更の完了と、変更後の日時・担当を伝える。",
    "slot_taken": "候補が直前に埋まったことを詫び、別候補または別日時の選択を促す。",
    "handoff_to_human": "無人では完結できない理由を簡潔に伝え、担当者が対応すると案内する。",
    "parse_failed": "聞き取れなかったことを詫び、希望日と時間帯の例を添えて言い直しを促す。",
    "reconfirm_yes_no": "何に対する確認かを明示し、はい/いいえでの返答を促す。",
    "conversation_expired": "一定時間が経過したため前回の未確定内容を破棄したことと、最初から案内することを伝える。",
    "conversation_restarted": "希望に沿って未確定内容を破棄し、予約を最初から案内することを伝える。",
    "conversation_abandoned": "今回は予約せず会話を終了したことを穏やかに受け止め、またの連絡を歓迎する。",
}


def _slot_details(context: dict) -> str:
    date = context.get("date") or ""
    start = context.get("start") or ""
    end = context.get("end") or ""
    practitioner = context.get("practitioner") or ""
    menu = context.get("menu") or ""
    parts = [f"{date} {start}〜{end}".strip(" 〜")]
    if practitioner:
        parts.append(f"担当: {practitioner}")
    if menu:
        parts.append(f"メニュー: {menu}")
    return "（".join(parts[:1]) + (f"（{'・'.join(parts[1:])}）" if len(parts) > 1 else "")


def _fallback(situation: str, context: dict) -> str:
    slot = _slot_details(context)
    alternatives = context.get("alternatives") or []
    if situation == "confirm_slot":
        note = f"{context['first_visit_note']}\n" if context.get("first_visit_note") else ""
        return f"{note}{slot}でよろしいでしょうか？\nはい / いいえ"
    if situation == "offer_alternatives":
        if not alternatives:
            return "申し訳ありません、ご希望に近い空き枠が見つかりませんでした。別のご希望日時を教えてください。"
        header = "空いているお時間をご案内します。" if context.get("vague") else "ご希望の時間は満席でしたので、近い空き枠をご案内します。"
        lines = [header, *(f"{index}. {item.get('label', '')}" for index, item in enumerate(alternatives, 1))]
        lines.append("ご希望の番号を返信してください。別の日時でもお探しできます。")
        text = "\n".join(lines)
        return f"{context['first_visit_note']}\n{text}" if context.get("first_visit_note") else text
    if situation == "usual_confirm":
        practitioner = f"・担当: {context['practitioner']}" if context.get("practitioner") else ""
        return f"いつもの{context.get('menu', 'メニュー')} {context.get('duration', '')}分{practitioner}でよろしいですか？\nはい / いいえ"
    if situation == "confirmed":
        return f"ご予約を確定しました。\n{slot}\nご来院をお待ちしております。"
    if situation == "cancel_done":
        return f"{slot}のご予約をキャンセルしました。" if slot else "ご予約をキャンセルしました。"
    if situation == "change_done":
        return f"ご予約を変更しました。\n{slot}\nご来院をお待ちしております。"
    if situation == "ask_missing":
        missing = "、".join(str(field) for field in context.get("missing_fields") or [])
        return f"恐れ入りますが、{missing or '不足している予約情報'}を教えてください。"
    if situation == "reconfirm_yes_no":
        return f"{context.get('what') or 'この内容'}について、はい / いいえで返信してください。"
    if situation == "ask_datetime" and context.get("purpose") == "予約変更":
        return "変更後の日時を教えてください。\n例: 明日の午後3時"
    if situation == "conversation_expired":
        return "一定時間が経過したため、前回の入力をリセットしました。予約を最初からご案内します。"
    if situation == "conversation_restarted":
        return "承知しました。前回の入力をリセットし、予約を最初からご案内します。"
    if situation == "conversation_abandoned":
        return "承知しました。今回は予約せず終了します。またご都合が決まりましたら、いつでもご連絡ください。"
    templates = {
        "ask_datetime": "ご希望の日時を教えてください。\n例: 明日の午後3時",
        "ask_menu": "ご希望のメニューを選んでください。",
        "parse_failed": "うまく聞き取れず申し訳ありません。ご希望の日にちと時間帯をもう一度教えていただけますか？\n例: 明日の午後3時ごろ",
        "handoff_to_human": "内容を確認のうえ担当者からご案内します。少々お待ちください。",
        "slot_taken": "申し訳ありません。候補枠が直前に埋まりました。別の候補またはご希望日時を教えてください。",
    }
    return templates.get(situation, "内容を確認いたします。")


def _is_grounded_reply(situation: str, context: dict, reply: str) -> bool:
    required_phrases = {
        "confirmed": "ご予約を確定しました",
        "cancel_done": "キャンセルしました",
        "change_done": "変更しました",
        "conversation_expired": "一定時間",
        "conversation_restarted": "最初",
    }
    required_phrase = required_phrases.get(situation)
    if required_phrase and required_phrase not in reply:
        return False
    if situation == "usual_confirm":
        usual_label = f"いつもの{context.get('menu', 'メニュー')} {context.get('duration', '')}分"
        if usual_label not in reply:
            return False
    if situation == "ask_datetime" and context.get("purpose") == "予約変更" and "変更後" not in reply:
        return False
    if situation == "offer_alternatives" and any(
        item.get("label") and item["label"] not in reply
        for item in context.get("alternatives") or []
    ):
        return False

    factual_keys = ("date", "start", "end", "practitioner", "menu", "duration")
    return all(
        str(context[key]) in reply
        for key in factual_keys
        if context.get(key) not in (None, "")
    )


async def compose_reply(situation: str, context: dict) -> str:
    """与えられた事実だけで短文を生成し、失敗時は必ず定型文を返す。"""
    fallback = _fallback(situation, context)
    try:
        from app.config import settings
        if not settings.gemini_api_key:
            return fallback
        import httpx

        situation_guide = SITUATION_GUIDES.get(situation, "確定事実だけを自然で簡潔な受付文として伝える。")
        prompt = f"""あなたは接骨院の受付ベテラン事務員です。患者へのLINE返信を作ります。
必ず守る:
- 下の「確定事実」に無い日時・空き状況・診療内容を新たに作らない。日時・担当名・番号・メニュー名は確定事実の値をそのまま使う。
- 敬語で簡潔に。1〜3文。絵文字は最大1つ。1メッセージ1論点。
- 医療的な指示・診断はしない（「湿布を」「安静に」等は書かない）。痛みには一言いたわる程度に留める。
- 患者の直前メッセージ(patient_message)があれば、まず一言受け止めてから本題に入る。
状況(situation)ごとの目的:
{situation_guide}
状況: {situation}
確定事実(JSON): {json.dumps(context, ensure_ascii=False, default=str)}
返信文だけを返す:"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
                headers={"x-goog-api-key": settings.gemini_api_key},
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 200}},
                timeout=10,
            )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text if text and _is_grounded_reply(situation, context, text) else fallback
    except Exception as error:
        logger.warning("LINE reply composition failed (situation=%s): %s", situation, error)
        return fallback