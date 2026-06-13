"""Calendar edge-case regression tests for shared My/JM behavior."""

import httpx
import pytest


NON_ERROR_STATUSES = {200, 302, 303, 307}


@pytest.mark.asyncio
async def test_jm_calendar_invalid_year_month_never_500(jm: httpx.AsyncClient):
    for query in (
        "year=99999&month=13",
        "year=2026&month=0",
        "year=2026&month=99",
    ):
        r = await jm.get(f"/calendar?{query}", follow_redirects=False)
        assert r.status_code in NON_ERROR_STATUSES


@pytest.mark.asyncio
async def test_jm_calendar_valid_month_still_renders(jm: httpx.AsyncClient):
    r = await jm.get("/calendar?year=2026&month=6")
    assert r.status_code == 200
    assert "2026" in r.text


@pytest.mark.asyncio
async def test_my_calendar_invalid_year_month_never_500(my: httpx.AsyncClient):
    setup = await my.post(
        "/setup",
        data={"name": "CalendarEdge"},
        headers={"origin": "http://test", "host": "test"},
        follow_redirects=False,
    )
    assert setup.status_code == 303

    for query in (
        "year=99999&month=13",
        "year=2026&month=0",
        "year=2026&month=99",
    ):
        r = await my.get(f"/calendar?{query}", follow_redirects=False)
        assert r.status_code in NON_ERROR_STATUSES


@pytest.mark.asyncio
async def test_my_calendar_valid_month_still_renders(my: httpx.AsyncClient):
    setup = await my.post(
        "/setup",
        data={"name": "CalendarValid"},
        headers={"origin": "http://test", "host": "test"},
        follow_redirects=False,
    )
    assert setup.status_code == 303

    r = await my.get("/calendar?year=2026&month=6")
    assert r.status_code == 200
    assert "2026" in r.text
