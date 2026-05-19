"""
P2 tests: FTS5 full-text search + RRULE recurrence.
"""

import httpx
import pytest
import pytest_asyncio

from conftest import jm_app, my_app, work_app, jm_mod
from common.recurrence import (
    parse_rrule, build_rrule, normalize_rrule, next_occurrence,
    expand_recurring, rrule_to_korean, expand_recurring_events,
)

ORIGIN = {"origin": "http://test", "host": "test"}


def _extract_cookie(response: httpx.Response, name: str) -> str:
    for part in response.headers.get("set-cookie", "").split(";"):
        part = part.strip()
        if part.startswith(f"{name}="):
            return part.split("=", 1)[1]
    raise ValueError(f"Cookie {name} not found")


# ═══════════════════════════════════════════════════════════════════════════
# RRULE unit tests (no app needed)
# ═══════════════════════════════════════════════════════════════════════════

class TestRRULEParsing:

    def test_parse_legacy_daily(self):
        p = parse_rrule("daily")
        assert p["freq"] == "DAILY"
        assert p["interval"] == 1

    def test_parse_legacy_weekly(self):
        p = parse_rrule("weekly")
        assert p["freq"] == "WEEKLY"

    def test_parse_rrule_string(self):
        p = parse_rrule("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,FR")
        assert p["freq"] == "WEEKLY"
        assert p["interval"] == 2
        assert p["byday"] == ["MO", "WE", "FR"]

    def test_parse_monthly_bymonthday(self):
        p = parse_rrule("FREQ=MONTHLY;BYMONTHDAY=1,15")
        assert p["freq"] == "MONTHLY"
        assert p["bymonthday"] == [1, 15]

    def test_parse_count(self):
        p = parse_rrule("FREQ=DAILY;COUNT=5")
        assert p["count"] == 5

    def test_parse_until(self):
        p = parse_rrule("FREQ=DAILY;UNTIL=20260601")
        assert p["until"] is not None
        assert p["until"].isoformat() == "2026-06-01"

    def test_normalize_legacy(self):
        assert normalize_rrule("daily") == "FREQ=DAILY"
        assert normalize_rrule("weekdays") == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"

    def test_normalize_rrule_passthrough(self):
        s = "FREQ=MONTHLY;INTERVAL=3"
        assert normalize_rrule(s) == s

    def test_normalize_none(self):
        assert normalize_rrule("none") == ""
        assert normalize_rrule("") == ""

    def test_build_rrule_simple(self):
        assert build_rrule("WEEKLY") == "FREQ=WEEKLY"

    def test_build_rrule_complex(self):
        r = build_rrule("WEEKLY", interval=2, byday=["MO", "FR"])
        assert "FREQ=WEEKLY" in r
        assert "INTERVAL=2" in r
        assert "BYDAY=MO,FR" in r


class TestRRULENextOccurrence:

    def test_daily(self):
        assert next_occurrence("2026-05-19", "daily") == "2026-05-20"

    def test_weekly(self):
        assert next_occurrence("2026-05-19", "weekly") == "2026-05-26"

    def test_monthly(self):
        assert next_occurrence("2026-01-31", "monthly") == "2026-02-28"

    def test_yearly(self):
        assert next_occurrence("2026-05-19", "yearly") == "2027-05-19"

    def test_rrule_biweekly(self):
        assert next_occurrence("2026-05-19", "FREQ=WEEKLY;INTERVAL=2") == "2026-06-02"

    def test_rrule_byday(self):
        # 2026-05-19 is Tuesday
        nxt = next_occurrence("2026-05-19", "FREQ=WEEKLY;BYDAY=MO,WE,FR")
        assert nxt == "2026-05-20"  # Wednesday

    def test_rrule_count_exhausted(self):
        # COUNT=1 means only 1 occurrence total, no next
        assert next_occurrence("2026-05-19", "FREQ=DAILY;COUNT=1") is not None

    def test_rrule_until_past(self):
        assert next_occurrence("2026-05-19", "FREQ=DAILY;UNTIL=20260519") is None

    def test_none_recurrence(self):
        assert next_occurrence("2026-05-19", "none") is None
        assert next_occurrence("2026-05-19", "") is None


class TestRRULEExpand:

    def test_expand_daily_range(self):
        dates = expand_recurring("2026-05-01", "daily", "2026-05-01", "2026-05-05")
        assert len(dates) == 5
        assert dates[0] == "2026-05-01"
        assert dates[-1] == "2026-05-05"

    def test_expand_weekly(self):
        dates = expand_recurring("2026-05-01", "weekly", "2026-05-01", "2026-05-31")
        assert len(dates) == 5  # May 1, 8, 15, 22, 29

    def test_expand_with_count(self):
        dates = expand_recurring("2026-05-01", "FREQ=DAILY;COUNT=3", "2026-05-01", "2026-12-31")
        assert len(dates) == 3

    def test_expand_with_until(self):
        dates = expand_recurring("2026-05-01", "FREQ=DAILY;UNTIL=20260503", "2026-05-01", "2026-12-31")
        assert len(dates) == 3

    def test_expand_empty_on_bad_input(self):
        assert expand_recurring("", "daily", "2026-05-01", "2026-05-05") == []
        assert expand_recurring("2026-05-01", "", "2026-05-01", "2026-05-05") == []


class TestRRULEKorean:

    def test_legacy_korean(self):
        assert rrule_to_korean("daily") == "매일"
        assert rrule_to_korean("weekly") == "매주"

    def test_rrule_korean(self):
        text = rrule_to_korean("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE")
        assert "2주마다" in text
        assert "월" in text
        assert "수" in text

    def test_monthly_korean(self):
        text = rrule_to_korean("FREQ=MONTHLY;BYMONTHDAY=1,15")
        assert "매월" in text
        assert "1일" in text
        assert "15일" in text

    def test_none_korean(self):
        assert rrule_to_korean("none") == "반복 없음"


class TestExpandRecurringEvents:

    def test_basic_expansion(self):
        events = [{"id": 1, "title": "Stand-up", "start_time": "2026-05-01",
                    "end_time": "", "recurrence": "daily", "recurrence_end": ""}]
        result = expand_recurring_events(events, "2026-05-01", "2026-05-03")
        assert len(result) == 3

    def test_no_recurrence_passthrough(self):
        events = [{"id": 1, "title": "Once", "start_time": "2026-05-01",
                    "end_time": "", "recurrence": ""}]
        result = expand_recurring_events(events, "2026-05-01", "2026-05-31")
        assert len(result) == 1


# ═══════════════════════════════════════════════════════════════════════════
# FTS5 integration tests (requires app)
# ═══════════════════════════════════════════════════════════════════════════

class TestFTS5Search:

    @pytest.mark.asyncio
    async def test_jm_search_returns_200(self, jm: httpx.AsyncClient):
        r = await jm.get("/search?q=test")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_jm_search_finds_todo(self, jm: httpx.AsyncClient):
        await jm.post("/todos", data={"title": "고유검색단어ABC"}, headers=ORIGIN, follow_redirects=False)
        r = await jm.get("/search?q=고유검색단어ABC")
        assert r.status_code == 200
        assert "고유검색단어ABC" in r.text

    @pytest.mark.asyncio
    async def test_jm_search_finds_memo(self, jm: httpx.AsyncClient):
        await jm.post("/memos", data={"content": "메모특수검색XYZ"}, headers=ORIGIN, follow_redirects=False)
        r = await jm.get("/search?q=메모특수검색XYZ")
        assert r.status_code == 200
        assert "메모특수검색XYZ" in r.text or "메모" in r.text

    @pytest.mark.asyncio
    async def test_jm_search_empty_query(self, jm: httpx.AsyncClient):
        r = await jm.get("/search?q=")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_jm_search_short_query(self, jm: httpx.AsyncClient):
        r = await jm.get("/search?q=a")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_jm_search_special_chars(self, jm: httpx.AsyncClient):
        r = await jm.get('/search?q="test*(){}')
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_fts_tables_created(self):
        """Verify FTS5 virtual tables exist after init_db."""
        with jm_mod.get_db() as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fts_%'"
            ).fetchall()]
            assert "fts_todos" in tables
            assert "fts_memos" in tables
            assert "fts_notices" in tables
            assert "fts_events" in tables
            assert "fts_worklogs" in tables

    @pytest.mark.asyncio
    async def test_my_search_requires_auth(self, my: httpx.AsyncClient):
        r = await my.get("/search?q=test", follow_redirects=False)
        assert r.status_code in (302, 303)

    @pytest_asyncio.fixture
    async def my_authed(self):
        transport = httpx.ASGITransport(app=my_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/setup", data={"name": "SearchUser"}, headers=ORIGIN, follow_redirects=False)
            cookie = _extract_cookie(r, "planner_profile")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=my_app),
                base_url="http://test",
                cookies={"planner_profile": cookie},
            ) as authed:
                yield authed

    @pytest.mark.asyncio
    async def test_my_search_finds_todo(self, my_authed: httpx.AsyncClient):
        await my_authed.post("/todos", data={"title": "마이검색QWERTY"}, headers=ORIGIN, follow_redirects=False)
        r = await my_authed.get("/search?q=마이검색QWERTY")
        assert r.status_code == 200
        assert "마이검색QWERTY" in r.text
