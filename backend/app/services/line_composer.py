"""LINE autopilot 向けの安全な返信文生成。"""
from __future__ import annotations

import json
import logging
import re


logger = logging.getLogger(__name__)

SITUATION_GUIDES = {
    "confirm_slot": "提示した日時・担当・メニューを省略せず、この内容で良いか確認する。はい/いいえで答えられると伝える。",
    "offer_alternatives": "候補を番号付きで見やすく並べ、希望する番号で選べると伝える。候補が空なら別の希望日時を尋ねる。所要時間が通常と異なる場合は、その所要時間を必ず明示する。料金には触れない。",
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
    "handoff_to_human": "担当者からご連絡することだけを簡潔に伝える。引き継ぐ理由や原因は推測しないし説明もしない。",
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
    "answer_question": "確定事実にあるシステムの値だけを根拠に質問へ答える。事実に無いことは答えず、推測もしない。",
    "price_to_staff": "料金は金額を一切述べず、スタッフから案内すると伝える。",
    "no_candidates": "ご希望の条件では空きがなかったことを伝え、別の日や時間帯を提案して次の選択肢を示す。黙って終わらせない。",
    "closed_day": "希望された日が休診日であることを正しく伝える。『予約がいっぱい』『満席』とは絶対に言い換えない。診療している直近の日を示して希望を尋ねる。",
    "small_talk": "予約以外の短いやりとりに自然に応じる。用事があれば承る姿勢を一言添える。予約の話を無理に持ち出さない。",
    "waiting_ack": "待たせている催促へ素直に応じる。原因や障害を推測せず、確定事実にある現状だけを伝える。",
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
    if situation == "no_candidates":
        return "ご希望の条件では空きがございませんでした。別の日や時間帯を教えていただければ、あらためてお探しします。"
    if situation == "closed_day":
        next_days = context.get("next_open_dates") or []
        guide = f"\n直近の診療日は {' / '.join(str(day) for day in next_days)} です。" if next_days else ""
        return (
            f"申し訳ございません。{context.get('date', 'ご希望の日')}は"
            f"{context.get('reason') or '休診日'}のため、ご予約を承れません。{guide}\n"
            "ご都合のよい日を教えていただけますか。"
        )
    if situation == "price_to_staff":
        return "料金についてはスタッフからあらためてご案内いたします。"
    if situation == "small_talk":
        return "ご連絡ありがとうございます。ご用がありましたら、いつでもお知らせください。"
    if situation == "waiting_ack":
        return "お待たせして申し訳ございません。引き続き承っておりますので、ご希望を教えていただけますでしょうか。"
    if situation == "answer_question":
        return "ご質問の内容を確認のうえ、担当者からご案内いたします。"
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


_SYSTEM_STATE_WORDS = (
    "システム", "サーバ", "障害", "エラー", "不具合", "メンテナンス", "故障", "ダウン", "回線",
)
_SYMPTOM_REPLY_WORDS = (
    "痛み", "痛く", "痛い", "症状", "患部", "お加減", "体調", "お大事", "お怪我", "怪我",
)
_SYMPTOM_CONTEXT_WORDS = (
    "痛", "症状", "つら", "辛い", "こり", "肩こり", "しびれ", "ゆが", "ぐっくり", "寝違え",
    "違和感", "怪我", "ケガ", "挿間板", "のばせ", "リハビ", "治療", "痛みを",
)


# 院の仕組みを勝手に説明する文（「マッスルセラピーは1枠10分で組んでおります」等）の検出。
# 実際に10分枠の予約を確定させたうえで、それらしい理由を作文した事故があったため。
_SPEC_CLAIM_PATTERNS = (
    re.compile(r"(?:1|一)\s*枠"),
    re.compile(r"枠(?:は|を|で)?\s*\d{1,3}\s*分"),
    # 「10分単位で区切ってお取りしています」のような院の仕組みの説明のみを拾う。
    # 「60分で承りました」のような通常の受け答えは弾かない。
    re.compile(r"\d{1,3}\s*分(?:単位|刻み|区切り|ずつ)\s*で\s*(?:組|区切|設定|お取り|運用)"),
    re.compile(r"\d{1,3}\s*分\s*で\s*(?:組んで|区切って|設定して)"),
    re.compile(r"(?:仕組み|システム上|規定|ルール|方針)(?:上|で|では)"),
)

_MENU_DURATION_PATTERN = re.compile(r"(\d{1,3})\s*分")


_RETRY_NOTES = {
    "contradiction": "\n前回の返信は確定事実と異なる日時を含んでいました。確定事実の日時だけを使って書き直してください。",
    "unsupported_claim": "\n前回の返信は確定事実に無いシステム状態や患者の症状の推測を含んでいました。原因・障害・体調の推測には触れず、確定事実にあることだけで書き直してください。",
    "spec_claim": "\n前回の返信は院の枠の組み方や施術時間のルールを勝手に説明していました。院の仕組みには触れず、確定情報にある施術時間だけを使って書き直してください。",
}


def _allowed_durations(context: dict) -> set[int]:
    """返信で言及してよい「◯分」の集合（確定事実＋院の確定情報のメニュー時間）。"""
    allowed: set[int] = set()
    for key in ("duration", "duration_minutes", "search_duration_minutes"):
        value = context.get(key)
        if isinstance(value, (int, float)):
            allowed.add(int(value))
        elif isinstance(value, str) and value.isdigit():
            allowed.add(int(value))

    clinic = context.get("clinic") or {}
    for menu in clinic.get("menus") or []:
        for key in ("min_minutes", "max_minutes"):
            if isinstance(menu.get(key), int):
                allowed.add(menu[key])
    for candidate in context.get("alternatives") or []:
        if isinstance(candidate, dict) and isinstance(candidate.get("duration_minutes"), int):
            allowed.add(candidate["duration_minutes"])
    return allowed


def _has_spec_claim(context: dict, reply: str) -> bool:
    """院の仕組み・枠の組み方を作文していないか。"""
    if any(pattern.search(reply) for pattern in _SPEC_CLAIM_PATTERNS):
        return True
    # 確定事実にない施術時間を語っていないか（10分予約の作り話対策）
    allowed = _allowed_durations(context)
    if allowed:
        mentioned = {int(match.group(1)) for match in _MENU_DURATION_PATTERN.finditer(reply)}
        if mentioned and not mentioned.issubset(allowed):
            return True
    return False


# 「月曜日のご予約ですね」のように、患者が述べていない曜日を確定として書く事故の検出。
# _DATE_PATTERN は 8/18 形式しか見ないため、曜日の断言は素通りしていた。
_WEEKDAY_ASSERTION_PATTERN = re.compile(r"[月火水木金土日]曜")
_DATE_BEARING_KEYS = ("date", "start", "assumed_date", "next_open_dates", "alternatives")


def _asserts_unestablished_weekday(context: dict, reply: str) -> bool:
    """日付が確定していないのに曜日を決まったこととして書いていないか。"""
    if not _WEEKDAY_ASSERTION_PATTERN.search(reply):
        return False
    # 確定事実に日付系の情報が1つでもあれば、曜日への言及は根拠がある
    for key in _DATE_BEARING_KEYS:
        if context.get(key):
            return False
    # 休診日の案内は院の確定情報が根拠なので許可する
    if context.get("closed_days") or (context.get("clinic") or {}).get("closed_days"):
        return False
    return True


def _has_unsupported_claim(context: dict, reply: str) -> bool:
    """確定事実に無いシステム状態や症状の推測を患者へ送らないための検出。"""
    if _asserts_unestablished_weekday(context, reply):
        return True
    if any(word in reply for word in _SYSTEM_STATE_WORDS) and not context.get("system_status"):
        return True
    if any(word in reply for word in _SYMPTOM_REPLY_WORDS):
        context_text = json.dumps(context, ensure_ascii=False, default=str)
        if not any(word in context_text for word in _SYMPTOM_CONTEXT_WORDS):
            return True
    return False


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
        # 院の確定情報は別枠で提示する（LLMが休診日や施術時間を推測で語らないための土台）
        from app.services.clinic_context import format_clinic_context_for_prompt

        clinic_block = format_clinic_context_for_prompt(context.get("clinic") or {})
        facts = {
            key: value
            for key, value in context.items()
            if key not in {"recent_history", "clinic"}
        }
        prompt = f"""あなたは接骨院の受付を長年担当しているベテラン事務員です。患者へのLINE返信を、あなた自身の言葉で自然に書いてください。

【あなたの役割】
患者の言葉をそのまま受け止め、必要なことだけを、感じよく、短く伝える。機械的な定型文は書かない。

【厳守】
- 下の「院の確定情報」と「確定事実」に無い日時・空き状況・診療内容を新たに作らない（事実の捏造だけが禁止事項）。
- 確定事実にある日時・担当名・メニュー名に言及するときは、その値を正確に使う（言及しないこと自体は自由）。
- 休診日に予約は受けられない。休診日を「予約がいっぱい」「満席」と言い換えない。休診であることを正しく伝える。
- 患者が述べていない日付・曜日を、決まったことのように書かない。
  確定事実に日付が無いのに「◯曜日のご予約ですね」と書くのは禁止。分からなければ日付を尋ねる。
  assumed_date がある場合は患者が今回述べた日ではないため、断言せず「前回◯◯とのことでしたが、それでよろしいですか」と確認する。
- 院の仕組み・枠の組み方・施術時間のルールを勝手に説明しない（「1枠◯分で組んでいます」等）。
  施術時間について触れるときは、院の確定情報にあるメニューの施術時間だけを使う。
- システムの状態・障害・エラー・処理状況について、確定事実に無いことを書かない。
- 患者の症状や体調について、確定事実に無い推測を書かない（症状の話が出ていない場面で「お痛みは大丈夫ですか」などと書かない）。
- 担当者に代わる理由を創作しない。理由が確定事実に無ければ、理由には一切触れず引き継ぎだけを伝える。
- 料金・費用・保険適用の可否には答えない。金額を一切書かず、スタッフから案内すると伝える。
- 敬語。1〜3文。絵文字は最大1つ。1メッセージ1論点。
- 医療的な指示・診断はしない。痛みには一言いたわる程度に留める。
- 患者の直前メッセージがあれば、まず一言受け止めてから本題に入る。
- 「はい/いいえ」で答えてほしいときは、そう分かるように書く。

【院の確定情報】
{clinic_block}

【状況】{situation}: {situation_guide}
【直近の会話】{json.dumps(recent_history, ensure_ascii=False, default=str)}
【確定事実(JSON)】{json.dumps(facts, ensure_ascii=False, default=str)}

返信文だけを出力:"""
        async with httpx.AsyncClient() as client:
            reason = "contradiction"
            for attempt in range(2):
                retry_note = "" if attempt == 0 else _RETRY_NOTES[reason]
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
                if _has_temporal_contradiction(context, text):
                    reason = "contradiction"
                    continue
                if _has_unsupported_claim(context, text):
                    reason = "unsupported_claim"
                    continue
                if _has_spec_claim(context, text):
                    reason = "spec_claim"
                    continue
                return text
        logger.error("LINE reply fallback situation=%s reason=%s", situation, reason)
        await _notify_fallback(situation, reason)
        return fallback
    except Exception as error:
        logger.error("LINE reply fallback situation=%s reason=api_error error=%s", situation, error)
        await _notify_fallback(situation, "api_error")
        return fallback