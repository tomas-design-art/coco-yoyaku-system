"""LINE autopilot 向けの安全な返信文生成。"""
from __future__ import annotations

import json
import logging
import re


logger = logging.getLogger(__name__)

SITUATION_GUIDES = {
    "confirm_slot": "提示した日時・担当・メニューを省略せず、この内容で良いか確認する。はい/いいえで答えられると伝える。",
    "offer_alternatives": "候補を番号付きで見やすく並べ、希望する番号で選べると伝える。候補が空なら別の希望日時を尋ねる。",
    "usual_confirm": "いつものメニュー・所要時間・担当を提示し、この内容で良いか確認する。",
    "ask_datetime": "症状があれば一言いたわった上で、希望日時を尋ねる。",
    "ask_time_for_date": "受け取った希望日を認識したと示し、その日の空き候補があれば提示して希望時刻を尋ねる。",
    "ask_date_for_time": "受け取った希望時刻を認識したと示し、希望日だけを尋ねる。",
    "ask_missing": "不足項目だけを責めずに尋ねる。複数ある場合も確定事実の項目名を使う。",
    "ask_menu": "予約に必要なメニュー選択を簡潔に促す。",
    "confirmed": "予約が確定したことと、確定した日時・担当・メニューを伝えて来院を歓迎する。",
    "cancel_done": "指定された予約のキャンセル完了を事実だけで伝える。",
    "cancel_confirm": "対象予約の日時を示し、本当にキャンセルしてよいか、はい/いいえで確認する。",
    "change_done": "予約変更の完了と、変更後の日時・担当を伝える。",
    "slot_taken": "候補が直前に埋まったことを詫び、別候補または別日時の選択を促す。",
    "handoff_to_human": "無人では完結できない理由を簡潔に伝え、担当者が対応すると案内する。",
    "parse_failed": "聞き取れなかったことを詫び、希望日と時間帯の例を添えて言い直しを促す。",
    "reconfirm_yes_no": "何に対する確認かを明示し、はい/いいえでの返答を促す。",
    "conversation_expired": "一定時間が経過したため前回の未確定内容を破棄したことと、最初から案内することを伝える。",
    "conversation_restarted": "希望に沿って未確定内容を破棄し、予約を最初から案内することを伝える。",
    "conversation_abandoned": "今回は予約せず会話を終了したことを穏やかに受け止め、またの連絡を歓迎する。",
    "cancel_failed": "キャンセル処理が完了しなかったことを詫び、再試行か担当者対応を案内する。",
    "cancel_aborted": "キャンセルを取りやめたことを自然に伝える。",
    "change_target_missing": "変更対象の予約を確認できないため、改めて変更希望を伝えてもらう。",
    "change_aborted": "提示した変更候補を取りやめ、別の希望日時を尋ねる。",
    "ask_full_name": "本人確認に必要なフルネームだけを丁寧に尋ねる。",
    "identity_retry": "本人確認情報を見つけられなかったため、最初から入力し直せるよう案内する。",
    "usual_accepted": "いつもの内容を受け付けたことを自然に伝え、足りない日時だけを尋ねる。",
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
    if situation == "cancel_confirm":
        return f"{slot}のご予約をキャンセルしてよろしいですか？\nはい / いいえ"
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
    if situation == "ask_time_for_date":
        return f"{context.get('date', 'その日')}ですね。ご希望の時間を教えてください。"
    if situation == "ask_date_for_time":
        return f"{context.get('time', 'その時間')}ですね。ご希望の日を教えてください。"
    if situation == "cancel_failed":
        return "キャンセル処理を完了できませんでした。もう一度お試しいただくか、担当者へご連絡ください。"
    if situation == "cancel_aborted":
        return "承知しました。キャンセルは取りやめました。"
    if situation == "change_target_missing":
        return "変更する予約を確認できませんでした。改めて予約変更のご希望をお知らせください。"
    if situation == "change_aborted":
        return "変更候補を取りやめました。別のご希望日時を教えてください。"
    if situation == "ask_full_name":
        return "確認のため、フルネームをもう一度教えてください。"
    if situation == "identity_retry":
        return "確認情報が見つかりませんでした。恐れ入りますが、最初から入力をお願いします。"
    if situation == "usual_accepted":
        return "いつもの内容で承りました。ご希望日時を教えてください。"
    templates = {
        "ask_datetime": "ご希望の日時を教えてください。\n例: 明日の午後3時",
        "ask_menu": "ご希望のメニューを選んでください。",
        "parse_failed": "うまく聞き取れず申し訳ありません。ご希望の日にちと時間帯をもう一度教えていただけますか？\n例: 明日の午後3時ごろ",
        "handoff_to_human": "内容を確認のうえ担当者からご案内します。少々お待ちください。",
        "slot_taken": "申し訳ありません。候補枠が直前に埋まりました。別の候補またはご希望日時を教えてください。",
    }
    return templates.get(situation, "内容を確認いたします。")


_TIME_PATTERN = re.compile(r"(?<!\d)([0-2]?\d)[:：]([0-5]\d)|(?<!\d)([0-2]?\d)時(?:([0-5]?\d)分)?")
_DATE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})[月/]\s*(\d{1,2})日?")


def _temporal_facts(value: object) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    times: set[tuple[int, int]] = set()
    dates: set[tuple[int, int]] = set()

    def collect(item: object, key: str | None = None) -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                if child_key not in {"patient_message", "recent_history"}:
                    collect(child, child_key)
            return
        if isinstance(item, list):
            for child in item:
                collect(child, key)
            return
        if item in (None, ""):
            return
        text = str(item)
        if key in {"start", "end", "time"}:
            for match in _TIME_PATTERN.finditer(text):
                hour = int(match.group(1) or match.group(3))
                minute = int(match.group(2) or match.group(4) or 0)
                times.add((hour, minute))
        if key == "date":
            iso_match = re.search(r"\d{4}-(\d{1,2})-(\d{1,2})", text)
            if iso_match:
                dates.add((int(iso_match.group(1)), int(iso_match.group(2))))
            for match in _DATE_PATTERN.finditer(text):
                dates.add((int(match.group(1)), int(match.group(2))))

    collect(value)
    return times, dates


def _has_temporal_contradiction(context: dict, reply: str) -> bool:
    allowed_times, allowed_dates = _temporal_facts(context)
    reply_times = {
        (int(match.group(1) or match.group(3)), int(match.group(2) or match.group(4) or 0))
        for match in _TIME_PATTERN.finditer(reply)
    }
    reply_dates = {
        (int(match.group(1)), int(match.group(2)))
        for match in _DATE_PATTERN.finditer(reply)
    }
    return bool((reply_times and not reply_times.issubset(allowed_times)) or (reply_dates and not reply_dates.issubset(allowed_dates)))


async def _notify_fallback(situation: str, reason: str) -> None:
    try:
        from app.config import settings
        from app.services.line_reply import push_message

        admin_user_id = settings.admin_line_developer_user_id or settings.line_admin_user_id
        if admin_user_id:
            await push_message(
                admin_user_id,
                f"[LINE AI返信異常] AI返信に失敗したためテンプレで応答しました。situation={situation} reason={reason}",
            )
    except Exception as error:
        logger.error("LINE reply fallback notification failed situation=%s error=%s", situation, error)


async def compose_reply(situation: str, context: dict) -> str:
    """LLMの自然文を返し、通信不能または日時矛盾の再生成失敗時だけ定型文へ戻す。"""
    fallback = _fallback(situation, context)
    try:
        from app.config import settings
        if not settings.gemini_api_key:
            logger.error("LINE reply fallback situation=%s reason=api_error detail=missing_api_key", situation)
            await _notify_fallback(situation, "api_error")
            return fallback
        import httpx

        situation_guide = SITUATION_GUIDES.get(situation, "確定事実だけを自然で簡潔な受付文として伝える。")
        recent_history = context.get("recent_history") or []
        facts = {key: value for key, value in context.items() if key != "recent_history"}
        prompt = f"""あなたは接骨院の受付を長年担当しているベテラン事務員です。患者へのLINE返信を、あなた自身の言葉で自然に書いてください。

【あなたの役割】
患者の言葉をそのまま受け止め、必要なことだけを、感じよく、短く伝える。機械的な定型文は書かない。

【厳守】
- 下の「確定事実」に無い日時・空き状況・診療内容を新たに作らない（事実の捏造だけが禁止事項）。
- 確定事実にある日時・担当名・メニュー名に言及するときは、その値を正確に使う（言及しないこと自体は自由）。
- 敬語。1〜3文。絵文字は最大1つ。1メッセージ1論点。
- 医療的な指示・診断はしない。痛みには一言いたわる程度に留める。
- 患者の直前メッセージがあれば、まず一言受け止めてから本題に入る。
- 「はい/いいえ」で答えてほしいときは、そう分かるように書く。

【状況】{situation}: {situation_guide}
【直近の会話】{json.dumps(recent_history, ensure_ascii=False, default=str)}
【確定事実(JSON)】{json.dumps(facts, ensure_ascii=False, default=str)}

返信文だけを出力:"""
        async with httpx.AsyncClient() as client:
            for attempt in range(2):
                retry_note = "" if attempt == 0 else "\n前回の返信は確定事実と異なる日時を含んでいました。確定事実の日時だけを使って書き直してください。"
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
                    headers={"x-goog-api-key": settings.gemini_api_key},
                    json={"contents": [{"role": "user", "parts": [{"text": prompt + retry_note}]}], "generationConfig": {"temperature": 0, "maxOutputTokens": 200}},
                    timeout=10,
                )
                response.raise_for_status()
                text = response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                if not text:
                    raise ValueError("Gemini returned an empty reply")
                if not _has_temporal_contradiction(context, text):
                    return text
        logger.error("LINE reply fallback situation=%s reason=contradiction", situation)
        await _notify_fallback(situation, "contradiction")
        return fallback
    except Exception as error:
        logger.error("LINE reply fallback situation=%s reason=api_error error=%s", situation, error)
        await _notify_fallback(situation, "api_error")
        return fallback