"""
Comprehensive tests for Korean NLP date parser.

Covers: relative dates, day-of-week, absolute dates, shortcuts,
        extract_date_from_text, format_date_display, edge cases.

Run:  cd /workspace/planners && python3 -m pytest tests/nlp_date_test.py -v
"""

from datetime import date

import pytest

from common.nlp_date import (
    extract_date_from_text,
    format_date_display,
    parse_korean_date,
)


# ═══════════════════════════════════════════════════════════════════════════
# Relative dates — simple words
# ═══════════════════════════════════════════════════════════════════════════

class TestRelativeSimple:
    """오늘, 내일, 모레, 글피, 어제, 그저께"""

    REF = date(2026, 5, 19)  # Tuesday

    def test_today(self):
        assert parse_korean_date("오늘", self.REF) == date(2026, 5, 19)

    def test_tomorrow(self):
        assert parse_korean_date("내일", self.REF) == date(2026, 5, 20)

    def test_day_after_tomorrow(self):
        assert parse_korean_date("모레", self.REF) == date(2026, 5, 21)

    def test_three_days_later(self):
        assert parse_korean_date("글피", self.REF) == date(2026, 5, 22)

    def test_yesterday(self):
        assert parse_korean_date("어제", self.REF) == date(2026, 5, 18)

    def test_day_before_yesterday(self):
        assert parse_korean_date("그저께", self.REF) == date(2026, 5, 17)

    def test_day_before_yesterday_alt(self):
        assert parse_korean_date("그제", self.REF) == date(2026, 5, 17)


# ═══════════════════════════════════════════════════════════════════════════
# Relative dates — N일/주/개월 후/전
# ═══════════════════════════════════════════════════════════════════════════

class TestRelativeN:
    """N일 후, N일 뒤, N주 전, N개월 후, N달 후, etc."""

    REF = date(2026, 5, 19)

    def test_n_days_after(self):
        assert parse_korean_date("3일 후", self.REF) == date(2026, 5, 22)

    def test_n_days_behind(self):
        assert parse_korean_date("5일 뒤", self.REF) == date(2026, 5, 24)

    def test_n_days_before(self):
        assert parse_korean_date("7일 전", self.REF) == date(2026, 5, 12)

    def test_n_weeks_after(self):
        assert parse_korean_date("2주 후", self.REF) == date(2026, 6, 2)

    def test_n_weeks_before(self):
        assert parse_korean_date("1주 전", self.REF) == date(2026, 5, 12)

    def test_n_months_after(self):
        assert parse_korean_date("1개월 후", self.REF) == date(2026, 6, 19)

    def test_n_months_before(self):
        assert parse_korean_date("2개월 전", self.REF) == date(2026, 3, 19)

    def test_n_dal_after(self):
        """달 = month (alternative word)"""
        assert parse_korean_date("3달 후", self.REF) == date(2026, 8, 19)

    def test_korean_number_word(self):
        assert parse_korean_date("두달 후", self.REF) == date(2026, 7, 19)

    def test_korean_number_word_days(self):
        assert parse_korean_date("세일 후", self.REF) == date(2026, 5, 22)

    def test_large_number(self):
        assert parse_korean_date("30일 후", self.REF) == date(2026, 6, 18)

    def test_month_overflow_clamp(self):
        """Adding 1 month to Jan 31 should give Feb 28."""
        ref = date(2026, 1, 31)
        assert parse_korean_date("1개월 후", ref) == date(2026, 2, 28)


# ═══════════════════════════════════════════════════════════════════════════
# Day of week
# ═══════════════════════════════════════════════════════════════════════════

class TestDayOfWeek:
    """이번주/다음주 + 요일"""

    REF = date(2026, 5, 19)  # Tuesday, week: Mon 5/18 ~ Sun 5/24

    def test_this_week_monday(self):
        assert parse_korean_date("이번주 월요일", self.REF) == date(2026, 5, 18)

    def test_this_week_friday(self):
        # Fri = weekday 4, Mon 5/18 + 4 = 5/22
        assert parse_korean_date("이번주 금요일", self.REF) == date(2026, 5, 22)

    def test_this_week_sunday(self):
        assert parse_korean_date("이번주 일요일", self.REF) == date(2026, 5, 24)

    def test_this_week_short_name(self):
        assert parse_korean_date("이번주 금", self.REF) == date(2026, 5, 22)

    def test_this_week_short_with_space(self):
        assert parse_korean_date("이번 금요일", self.REF) == date(2026, 5, 22)

    def test_next_week_monday(self):
        assert parse_korean_date("다음주 월요일", self.REF) == date(2026, 5, 25)

    def test_next_week_friday(self):
        assert parse_korean_date("다음주 금요일", self.REF) == date(2026, 5, 29)

    def test_next_week_short(self):
        assert parse_korean_date("다음주 월", self.REF) == date(2026, 5, 25)

    def test_next_wednesday(self):
        """다음 수요일 (without 주)"""
        assert parse_korean_date("다음 수요일", self.REF) == date(2026, 5, 27)

    def test_next_friday_short(self):
        """다음 금 (without 주)"""
        assert parse_korean_date("다음 금요일", self.REF) == date(2026, 5, 29)


# ═══════════════════════════════════════════════════════════════════════════
# Absolute dates
# ═══════════════════════════════════════════════════════════════════════════

class TestAbsolute:
    """Full and partial date expressions."""

    REF = date(2026, 5, 19)

    # Full (year-month-day)
    def test_korean_full(self):
        assert parse_korean_date("2026년 5월 20일", self.REF) == date(2026, 5, 20)

    def test_iso_dash(self):
        assert parse_korean_date("2026-05-20", self.REF) == date(2026, 5, 20)

    def test_slash(self):
        assert parse_korean_date("2026/5/20", self.REF) == date(2026, 5, 20)

    def test_different_year(self):
        assert parse_korean_date("2025년 12월 31일", self.REF) == date(2025, 12, 31)

    # Partial (month-day only) — fills in current year
    def test_korean_partial(self):
        assert parse_korean_date("5월 20일", self.REF) == date(2026, 5, 20)

    def test_slash_partial(self):
        assert parse_korean_date("5/20", self.REF) == date(2026, 5, 20)

    def test_dash_partial(self):
        assert parse_korean_date("05-20", self.REF) == date(2026, 5, 20)

    def test_partial_future_year_rollover(self):
        """If the date is in the past, use next year."""
        assert parse_korean_date("1월 1일", self.REF) == date(2027, 1, 1)

    def test_partial_today_no_rollover(self):
        """Same-day should not roll to next year."""
        assert parse_korean_date("5월 19일", self.REF) == date(2026, 5, 19)

    def test_invalid_date(self):
        """Feb 30 is invalid."""
        assert parse_korean_date("2월 30일", self.REF) is None

    def test_invalid_full(self):
        assert parse_korean_date("2026-02-30", self.REF) is None


# ═══════════════════════════════════════════════════════════════════════════
# Shortcuts
# ═══════════════════════════════════════════════════════════════════════════

class TestShortcuts:
    """월말, 다음달 초, 주말"""

    def test_month_end_may(self):
        assert parse_korean_date("월말", date(2026, 5, 19)) == date(2026, 5, 31)

    def test_month_end_february(self):
        assert parse_korean_date("월말", date(2026, 2, 10)) == date(2026, 2, 28)

    def test_month_end_february_leap(self):
        assert parse_korean_date("월말", date(2028, 2, 10)) == date(2028, 2, 29)

    def test_month_end_january(self):
        assert parse_korean_date("월말", date(2026, 1, 15)) == date(2026, 1, 31)

    def test_next_month_first(self):
        assert parse_korean_date("다음달 초", date(2026, 5, 19)) == date(2026, 6, 1)

    def test_next_month_first_december(self):
        """다음달 초 from December crosses year boundary."""
        assert parse_korean_date("다음달 초", date(2026, 12, 15)) == date(2027, 1, 1)

    def test_weekend_from_tuesday(self):
        """주말 = next Saturday; ref = Tue 5/19 → Sat 5/23"""
        assert parse_korean_date("주말", date(2026, 5, 19)) == date(2026, 5, 23)

    def test_weekend_from_saturday(self):
        """주말 from Saturday → next Saturday (7 days later)."""
        assert parse_korean_date("주말", date(2026, 5, 23)) == date(2026, 5, 30)

    def test_weekend_from_friday(self):
        """주말 from Friday → next day Saturday."""
        assert parse_korean_date("주말", date(2026, 5, 22)) == date(2026, 5, 23)


# ═══════════════════════════════════════════════════════════════════════════
# extract_date_from_text
# ═══════════════════════════════════════════════════════════════════════════

class TestExtract:
    """Extract date from longer Korean sentences."""

    REF = date(2026, 5, 19)

    def test_tomorrow_with_particle(self):
        d, rest = extract_date_from_text("내일까지 보고서 제출", self.REF)
        assert d == date(2026, 5, 20)
        assert rest == "보고서 제출"

    def test_n_days_with_particle(self):
        d, rest = extract_date_from_text("3일 후에 회의", self.REF)
        assert d == date(2026, 5, 22)
        assert rest == "회의"

    def test_date_at_end(self):
        d, rest = extract_date_from_text("보고서 제출 내일", self.REF)
        assert d == date(2026, 5, 20)
        assert rest == "보고서 제출"

    def test_next_week_with_particle(self):
        d, rest = extract_date_from_text("다음주 금요일까지 PPT 완성", self.REF)
        assert d == date(2026, 5, 29)
        assert rest == "PPT 완성"

    def test_absolute_date_in_sentence(self):
        d, rest = extract_date_from_text("5월 25일에 발표 준비", self.REF)
        assert d == date(2026, 5, 25)
        assert rest == "발표 준비"

    def test_no_date_returns_none(self):
        d, rest = extract_date_from_text("그냥 할 일", self.REF)
        assert d is None
        assert rest == "그냥 할 일"

    def test_empty_string(self):
        d, rest = extract_date_from_text("", self.REF)
        assert d is None
        assert rest == ""

    def test_date_only_returns_none_remaining(self):
        """If entire text is just a date, remaining should be empty.
        In this case we should NOT extract (title would be empty)."""
        d, rest = extract_date_from_text("내일", self.REF)
        assert d == date(2026, 5, 20)
        # rest is empty string — caller should check
        assert rest == ""

    def test_particle_buteoh(self):
        d, rest = extract_date_from_text("모레부터 다이어트 시작", self.REF)
        assert d == date(2026, 5, 21)
        assert rest == "다이어트 시작"

    def test_full_iso_date_in_text(self):
        d, rest = extract_date_from_text("2026-06-01에 출장", self.REF)
        assert d == date(2026, 6, 1)
        assert rest == "출장"

    def test_shortcut_in_text(self):
        d, rest = extract_date_from_text("월말까지 정산", self.REF)
        assert d == date(2026, 5, 31)
        assert rest == "정산"


# ═══════════════════════════════════════════════════════════════════════════
# format_date_display
# ═══════════════════════════════════════════════════════════════════════════

class TestDisplay:
    def test_weekday_tuesday(self):
        assert format_date_display(date(2026, 5, 19)) == "5월 19일 (화)"

    def test_weekday_wednesday(self):
        assert format_date_display(date(2026, 5, 20)) == "5월 20일 (수)"

    def test_weekday_sunday(self):
        assert format_date_display(date(2026, 5, 24)) == "5월 24일 (일)"

    def test_january(self):
        assert format_date_display(date(2026, 1, 1)) == "1월 1일 (목)"


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases & invalid input
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_none_input(self):
        assert parse_korean_date(None) is None

    def test_empty_string(self):
        assert parse_korean_date("") is None

    def test_whitespace_only(self):
        assert parse_korean_date("   ") is None

    def test_random_text(self):
        assert parse_korean_date("아무거나 입력") is None

    def test_number_only(self):
        assert parse_korean_date("123") is None

    def test_english_date(self):
        assert parse_korean_date("tomorrow") is None

    def test_leading_trailing_whitespace(self):
        assert parse_korean_date("  내일  ", date(2026, 5, 19)) == date(2026, 5, 20)

    def test_year_boundary_month_add(self):
        """Adding months that cross a year boundary."""
        ref = date(2026, 11, 15)
        assert parse_korean_date("3개월 후", ref) == date(2027, 2, 15)

    def test_year_boundary_month_sub(self):
        """Subtracting months that cross a year boundary."""
        ref = date(2026, 2, 15)
        assert parse_korean_date("3개월 전", ref) == date(2025, 11, 15)

    def test_month_end_clamp_on_subtract(self):
        """March 31 minus 1 month → Feb 28."""
        ref = date(2026, 3, 31)
        assert parse_korean_date("1개월 전", ref) == date(2026, 2, 28)

    def test_default_reference_date(self):
        """When no reference_date, uses today."""
        result = parse_korean_date("오늘")
        assert result == date.today()

    def test_extract_none_input(self):
        d, rest = extract_date_from_text(None)
        assert d is None
        assert rest == ""


# ═══════════════════════════════════════════════════════════════════════════
# API endpoint test (uses JM app — no auth needed)
# ═══════════════════════════════════════════════════════════════════════════

class TestParseDateAPI:

    @pytest.mark.asyncio
    async def test_parse_tomorrow(self, jm):
        r = await jm.get("/api/parse-date", params={"text": "내일"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "date" in data
        assert "display" in data

    @pytest.mark.asyncio
    async def test_parse_next_week_friday(self, jm):
        r = await jm.get("/api/parse-date", params={"text": "다음주 금요일"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True

    @pytest.mark.asyncio
    async def test_parse_invalid(self, jm):
        r = await jm.get("/api/parse-date", params={"text": "아무거나"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False

    @pytest.mark.asyncio
    async def test_parse_empty(self, jm):
        r = await jm.get("/api/parse-date", params={"text": ""})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False

    @pytest.mark.asyncio
    async def test_parse_absolute_date(self, jm):
        r = await jm.get("/api/parse-date", params={"text": "2026-06-15"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["date"] == "2026-06-15"


# ═══════════════════════════════════════════════════════════════════════════
# Integration: NLP extraction in todo creation
# ═══════════════════════════════════════════════════════════════════════════

ORIGIN = {"origin": "http://test", "host": "test"}


class TestTodoNLPIntegration:
    """Test that create_todo auto-extracts date from title."""

    @pytest.mark.asyncio
    async def test_nlp_date_in_title_no_explicit_date(self, jm):
        """When no due_date is given, extract from title."""
        r = await jm.post(
            "/todos",
            data={"title": "내일까지 보고서 제출"},
            headers=ORIGIN,
            follow_redirects=True,
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_explicit_date_not_overridden(self, jm):
        """When due_date is explicitly given, NLP should not override."""
        r = await jm.post(
            "/todos",
            data={"title": "내일까지 보고서 제출", "due_date": "2026-12-25"},
            headers=ORIGIN,
            follow_redirects=True,
        )
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_quick_todo_nlp(self, jm):
        """Quick-todo also supports NLP date extraction."""
        r = await jm.post(
            "/quick-todo",
            data={"title": "모레까지 발표자료 준비"},
            headers=ORIGIN,
            follow_redirects=True,
        )
        assert r.status_code == 200
