"""JST (Asia/Tokyo) タイムゾーンユーティリティ"""
import zoneinfo
from datetime import datetime

JST = zoneinfo.ZoneInfo("Asia/Tokyo")


def now_jst() -> datetime:
    """Asia/Tokyo の現在時刻を返す (+09:00 オフセット付き)"""
    return datetime.now(JST)
