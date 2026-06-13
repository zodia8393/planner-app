from uuid import uuid4

import httpx
import pytest

from conftest import jm_mod, my_mod


ORIGIN = {"origin": "http://test", "host": "test"}


async def _setup_my_profile(client: httpx.AsyncClient) -> int:
    name = f"DashboardEmpty{uuid4().hex[:8]}"
    response = await client.post(
        "/setup",
        data={"name": name},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303

    with my_mod.get_db() as conn:
        row = conn.execute("SELECT id FROM profiles WHERE name=?", (name,)).fetchone()
    assert row is not None
    return int(row["id"])


def _clear_dashboard_data(mod, profile_id: int) -> None:
    with mod.get_db() as conn:
        for table in ("todos", "events", "memos", "work_logs"):
            conn.execute(f"DELETE FROM {table} WHERE profile_id=?", (profile_id,))


def _assert_dashboard_empty_state(html: str) -> None:
    assert 'id="dashboard-status-summary"' in html
    assert 'class="sr-only"' in html
    assert '<div id="dashboard-status-summary" class="sr-only" role="status" aria-live="polite" aria-atomic="true">' in html
    assert "대시보드 상태:" in html
    assert '<section id="dashboard-empty-state" class="work-card rounded-xl p-4 mb-4" role="status" aria-live="polite" aria-atomic="true" aria-labelledby="dashboard-empty-title">' in html
    assert 'id="dashboard-empty-title"' in html
    assert "아직 표시할 작업이 없습니다" in html
    assert "첫 할 일을 추가하면 오늘 진행률과 주간 플랜이 이곳에 채워집니다." in html
    assert 'href="/todos#new"' in html
    assert "empty-state-primary" in html
    assert 'aria-label="빠른 작업"' in html
    assert 'id="dashboardGrid"' in html


@pytest.mark.asyncio
async def test_jm_dashboard_renders_empty_state_when_core_data_is_empty(jm: httpx.AsyncClient):
    _clear_dashboard_data(jm_mod, 1)

    response = await jm.get("/")

    assert response.status_code == 200
    _assert_dashboard_empty_state(response.text)


@pytest.mark.asyncio
async def test_my_dashboard_renders_empty_state_when_core_data_is_empty(my: httpx.AsyncClient):
    profile_id = await _setup_my_profile(my)
    _clear_dashboard_data(my_mod, profile_id)

    response = await my.get("/")

    assert response.status_code == 200
    _assert_dashboard_empty_state(response.text)
