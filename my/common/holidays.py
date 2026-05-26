"""Korean public holidays for planner apps."""

__all__ = [
    "KOREAN_HOLIDAYS",
    "get_holidays_for_month",
]

KOREAN_HOLIDAYS: dict[str, str] = {
    # 2025
    "2025-01-01": "신정",
    "2025-01-28": "설날 연휴",
    "2025-01-29": "설날",
    "2025-01-30": "설날 연휴",
    "2025-03-01": "삼일절",
    "2025-05-05": "어린이날",
    "2025-05-06": "대체공휴일(어린이날)",
    "2025-06-06": "현충일",
    "2025-08-15": "광복절",
    "2025-10-03": "개천절",
    "2025-10-05": "추석 연휴",
    "2025-10-06": "추석",
    "2025-10-07": "추석 연휴",
    "2025-10-08": "대체공휴일(추석)",
    "2025-10-09": "한글날",
    "2025-12-25": "성탄절",
    # 2026
    "2026-01-01": "신정",
    "2026-02-15": "설날 연휴",
    "2026-02-16": "설날",
    "2026-02-17": "설날 연휴",
    "2026-02-18": "대체공휴일(설날)",
    "2026-03-01": "삼일절",
    "2026-03-02": "대체공휴일(삼일절)",
    "2026-05-05": "어린이날",
    "2026-05-24": "석가탄신일",
    "2026-05-25": "대체공휴일(석가탄신일)",
    "2026-06-06": "현충일",
    "2026-08-15": "광복절",
    "2026-08-17": "대체공휴일(광복절)",
    "2026-09-24": "추석 연휴",
    "2026-09-25": "추석",
    "2026-09-26": "추석 연휴",
    "2026-10-03": "개천절",
    "2026-10-05": "대체공휴일(개천절)",
    "2026-10-09": "한글날",
    "2026-12-25": "성탄절",
}

# Add temporary holidays here:
# KOREAN_HOLIDAYS["2026-06-01"] = "임시공휴일"


def get_holidays_for_month(year: int, month: int) -> dict[str, str]:
    """Return holidays dict for a given month: ``{date_str: holiday_name}``."""
    prefix = f"{year:04d}-{month:02d}-"
    return {k: v for k, v in KOREAN_HOLIDAYS.items() if k.startswith(prefix)}


def get_holidays_for_year(year: int) -> dict[str, str]:
    """Return holidays dict for an entire year: ``{date_str: holiday_name}``."""
    prefix = f"{year:04d}-"
    return {k: v for k, v in KOREAN_HOLIDAYS.items() if k.startswith(prefix)}
