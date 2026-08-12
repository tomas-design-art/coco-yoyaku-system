"""LINEメッセージ解析エージェント"""
from datetime import timedelta
import logging
import json
import re
from typing import Optional

from app.utils.datetime_jst import now_jst

logger = logging.getLogger(__name__)

LINE_PARSE_PROMPT = """
あなたは接骨院の熟練した多言語予約秘書です。以下のLINEメッセージから予約情報を抽出してください。
今日の日付は {today}（{weekday}曜日）です。

メッセージは日本語・英語・中国語・韓国語など、どの言語でも届きます。入力言語を問わず意味を理解し、日付と時刻は必ず下記のJSON形式へ正規化してください。患者が既に本人確認済みの場合は、名前が本文になくても名前を推測・創作しないでください。

必ずJSONのみで返してください。説明文は禁止。

予約意図がある場合:
- has_reservation_intent: true
- customer_name: 顧客名（例: 田中五郎丸）
- date: 希望日（YYYY-MM-DD）
- time: 希望時間（HH:MM）
- menu_name: 施術メニュー（例: 保険診療 / 初診 / 骨盤矯正）
- missing_fields: 欠けている必須項目名の配列。必須項目は customer_name,date,time,menu_name

予約意図がない場合:
- has_reservation_intent: false
- summary: メッセージの要約

JSON形式で返してください。

日時解釈ルール:
- 朝=09:00、午前/午前中=10:00、昼=12:00、午後=14:00、夕方=17:00、夜=19:00
- 「明日」「明後日」「次の日曜日」「来週火曜日」などは、今日の日付を基準に未来の日付へ解決する
- 「次のX曜日」は、直近の次のX曜日とする。今日がX曜日なら7日後とする
- 時刻や日付が書かれていない予約希望は has_reservation_intent を true にし、該当する missing_fields を返す

メッセージ:
{message}

JSON:
"""


def _normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    s = re.sub(r"[\s\u3000]+", "", name.strip())
    if len(s) < 2:
        return None
    # LINE表示名のノイズ除去
    s = re.sub(r"(さん|様|ちゃん|くん)$", "", s)
    return s or None


def _extract_name(message: str) -> str | None:
    blacklist = ["受診", "予約", "希望", "お願いします", "お願い", "はじめて", "初めて"]

    # 「私は田中です」「田中五郎丸です」
    pats = [
        r"(?:名前|氏名)[は:：\s]*([一-龥々ぁ-んァ-ヶー\s\u3000]{2,20})",
        r"([一-龥々\s\u3000]{2,20})(?:です|と申します)",
    ]

    # フルネームらしい並び（姓 名）を優先
    m2 = re.search(r"([一-龥々]{1,6})[\s\u3000]([一-龥々]{1,8})", message)
    if m2:
        candidate = _normalize_name(m2.group(1) + m2.group(2))
        if candidate and not any(w in candidate for w in blacklist):
            return candidate

    for p in pats:
        m = re.search(p, message)
        if m:
            candidate = _normalize_name(m.group(1))
            if candidate and not any(w in candidate for w in blacklist):
                return candidate
    return None


def extract_full_name(message: str, profile_name: str | None = None) -> str | None:
    """初回登録向けにフルネーム候補を抽出する。"""
    name = _extract_name(message)
    if name:
        return name

    # 「山田 太郎」のような姓・名を厳しめに拾う
    spaced = re.search(r"([一-龥々]{1,8})[\s\u3000]+([一-龥々]{1,8})", message)
    if spaced:
        return _normalize_name(spaced.group(1) + spaced.group(2))

    # 連続漢字4文字以上をフルネーム候補として扱う
    joined = re.search(r"([一-龥々]{4,16})", message)
    if joined:
        return _normalize_name(joined.group(1))

    return _normalize_name(profile_name)


def _extract_menu(message: str) -> str | None:
    menu_map = {
        "保険診療": ["保険診療", "保険", "保険の治療"],
        "初診": ["初診", "はじめて", "初めて", "初めての受診"],
        "骨盤矯正": ["骨盤矯正", "骨盤"],
        "全身調整": ["全身調整", "全身"],
        "部分施術": ["部分施術", "部分"],
    }
    for canonical, keys in menu_map.items():
        if any(k in message for k in keys):
            return canonical
    return None


def _strip_courtesy_phrases(message: str) -> str:
    """日時抽出を誤らせる定型的な挨拶を除去する。"""
    cleaned = message or ""
    cleaned = re.sub(r"夜分\s*遅く(?:に)?\s*(?:失礼(?:します|いたします)?|すみません|申し訳ありません)?", "", cleaned)
    cleaned = re.sub(r"夜分(?:に)?\s*(?:失礼(?:します|いたします)?|すみません|申し訳ありません)", "", cleaned)
    return cleaned


def _extract_date_time(message: str) -> tuple[str | None, str | None]:
    message = _strip_courtesy_phrases(message)
    now = now_jst()
    date_val: str | None = None
    time_val: str | None = None

    # 相対日付
    if "明後日" in message:
        d = now.date() + timedelta(days=2)
        date_val = d.isoformat()
    elif "明日" in message:
        d = now.date() + timedelta(days=1)
        date_val = d.isoformat()
    elif "今日" in message:
        date_val = now.date().isoformat()

    # 絶対日付 YYYY/MM/DD, YYYY-MM-DD, 4/10, 4月10日
    m_year = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", message)
    if m_year:
        yy, mm, dd = map(int, m_year.groups())
        date_val = f"{yy:04d}-{mm:02d}-{dd:02d}"
    else:
        m = re.search(r"(\d{1,2})\s*[月/]\s*(\d{1,2})\s*日?", message)
        if m:
            mm = int(m.group(1))
            dd = int(m.group(2))
            yy = now.year + (1 if mm < now.month else 0)
            date_val = f"{yy:04d}-{mm:02d}-{dd:02d}"

    # 曜日表現: 来週/次の/今週/単独のX曜日
    if not date_val:
        weekday_map = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4, "土": 5, "日": 6}
        weekday_match = re.search(r"(?:(来週|次の|今週)\s*)?([月火水木金土日])曜(?:日)?", message)
        if weekday_match:
            qualifier, weekday_char = weekday_match.groups()
            target_weekday = weekday_map[weekday_char]
            days_ahead = (target_weekday - now.weekday()) % 7
            if qualifier == "来週":
                days_ahead += 7
            elif qualifier in {"次の", None} and days_ahead == 0:
                days_ahead = 7
            date_val = (now.date() + timedelta(days=days_ahead)).isoformat()

    # 時刻 午後3時, 午後3:30, 10時半
    m2 = re.search(r"(午前|午後)?\s*(\d{1,2})\s*[:：]\s*(\d{1,2})", message)
    if m2:
        period, hour, minute = m2.groups()
        hh = int(hour)
        mi = int(minute)
        if period == "午後" and 1 <= hh <= 11:
            hh += 12
        time_val = f"{hh:02d}:{mi:02d}"
    else:
        m3 = re.search(r"(午前|午後)?\s*(\d{1,2})\s*時\s*(半)?", message)
        if m3:
            period, hour, half = m3.groups()
            hh = int(hour)
            if period == "午後" and 1 <= hh <= 11:
                hh += 12
            time_val = f"{hh:02d}:{'30' if half else '00'}"

    if not time_val:
        if "午前中" in message or "午前" in message:
            time_val = "10:00"
        elif "お昼" in message or re.search(r"(?<!\d)昼(?!食)", message):
            time_val = "12:00"
        elif "午後" in message:
            time_val = "14:00"
        elif "夕方" in message:
            time_val = "17:00"
        elif "夜" in message or "晩" in message:
            time_val = "19:00"
        elif re.search(r"(?<!深)朝(?!ご飯)", message):
            time_val = "09:00"

    return date_val, time_val


def _compute_missing_fields(parsed: dict) -> list[str]:
    required = ["customer_name", "date", "time", "menu_name"]
    return [k for k in required if not parsed.get(k)]


async def parse_line_message(message: str, profile_name: str | None = None, previous: dict | None = None) -> dict:
    """LINEメッセージを解析して予約意図を判定"""
    # ルールベース優先 + 前回文脈補完
    result = _rule_based_parse(message, profile_name=profile_name, previous=previous)
    if result.get("has_reservation_intent") and result.get("date") and result.get("time"):
        result["missing_fields"] = _compute_missing_fields(result)
        return result

    # AI解析
    try:
        ai_result = await _ai_parse(message)
        if previous:
            for k in ["customer_name", "date", "time", "menu_name"]:
                ai_result[k] = ai_result.get(k) or previous.get(k)
        if not ai_result.get("customer_name"):
            ai_result["customer_name"] = _normalize_name(profile_name)
        ai_result["missing_fields"] = _compute_missing_fields(ai_result)
        if ai_result.get("has_reservation_intent"):
            return ai_result
        result["missing_fields"] = _compute_missing_fields(result)
        return result
    except Exception as e:
        logger.error(f"AI parse failed: {e}")
        fallback = _rule_based_parse(message, profile_name=profile_name, previous=previous)
        fallback["missing_fields"] = _compute_missing_fields(fallback)
        return fallback


def _rule_based_parse(message: str, profile_name: str | None = None, previous: dict | None = None) -> dict:
    """ルールベースのメッセージ解析"""
    previous = previous or {}
    # 予約キーワード
    reservation_keywords = [
        "予約", "よやく", "空き", "あき", "空いて", "空きますか", "取りたい", "お願い",
        "受診", "診察", "見てもら", "診てもら",
    ]
    has_intent = any(kw in message for kw in reservation_keywords)
    date_val, time_val = _extract_date_time(message)
    name_val = _extract_name(message)
    menu_val = _extract_menu(message)

    if not has_intent and not any([date_val, time_val, name_val, menu_val, previous]):
        return {"has_reservation_intent": False, "summary": message[:100]}

    result = {
        "has_reservation_intent": True,
        "customer_name": name_val or previous.get("customer_name") or _normalize_name(profile_name),
        "date": date_val or previous.get("date"),
        "time": time_val or previous.get("time"),
        "menu_name": menu_val or previous.get("menu_name"),
    }

    return result


async def _ai_parse(message: str) -> dict:
    """AI（Gemini）を使ったメッセージ解析"""
    from app.config import settings

    if settings.gemini_api_key:
        import httpx

        model = settings.gemini_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": settings.gemini_api_key}

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": "You are a helpful assistant. Respond with JSON only.\n\n"
                                 + LINE_PARSE_PROMPT.format(
                                     message=message,
                                     today=now_jst().date().isoformat(),
                                     weekday=["月", "火", "水", "木", "金", "土", "日"][now_jst().weekday()],
                                 )}
                    ],
                }
            ],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 512},
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                if parsed.get("customer_name"):
                    parsed["customer_name"] = _normalize_name(parsed.get("customer_name"))
                if parsed.get("time"):
                    tm = str(parsed["time"])
                    m = re.match(r"^(\d{1,2}):(\d{1,2})$", tm)
                    if m:
                        parsed["time"] = f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
                return parsed

    raise Exception("AI API key not configured")
