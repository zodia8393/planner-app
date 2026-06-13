from pathlib import Path
from uuid import uuid4

import httpx
import pytest


ORIGIN = {"origin": "http://test", "host": "test"}
ROOT = Path(__file__).resolve().parents[1]


async def _setup_my_profile(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/setup",
        data={"name": f"Quality{uuid4().hex[:8]}"},
        headers=ORIGIN,
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_my_dashboard_quick_actions_and_sync_banner(my: httpx.AsyncClient):
    await _setup_my_profile(my)
    response = await my.get("/")
    assert response.status_code == 200
    html = response.text
    assert "dashboard-quick-actions" in html
    assert "/todos#new" in html
    assert "/calendar#new" in html
    assert "/memos#new" in html
    assert 'id="offlineBanner"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'id="onboardingChecklist"' in html
    assert 'id="onboardingProgress"' in html
    assert "onboarding_done" not in html


@pytest.mark.asyncio
async def test_jm_dashboard_quick_actions_and_sync_banner(jm: httpx.AsyncClient):
    response = await jm.get("/")
    assert response.status_code == 200
    html = response.text
    assert "dashboard-quick-actions" in html
    assert "/todos#new" in html
    assert "/calendar#new" in html
    assert "/memos#new" in html
    assert 'id="offlineBanner"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert 'id="onboardingChecklist"' in html
    assert 'id="onboardingProgress"' in html
    assert "onboarding_done" not in html


@pytest.mark.asyncio
async def test_my_memo_empty_state_opens_form_cta(my: httpx.AsyncClient):
    await _setup_my_profile(my)
    response = await my.get("/memos?category_id=9999999")
    assert response.status_code == 200
    html = response.text
    assert 'id="memo-content"' in html
    assert 'data-action="open-memo-form"' in html
    assert "기존 기록 검색" in html


@pytest.mark.asyncio
async def test_jm_memo_empty_state_opens_form_cta(jm: httpx.AsyncClient):
    response = await jm.get("/memos?category_id=9999999")
    assert response.status_code == 200
    html = response.text
    assert 'id="memo-content"' in html
    assert 'data-action="open-memo-form"' in html
    assert "기존 기록 검색" in html


@pytest.mark.asyncio
async def test_my_calendar_empty_month_cta(my: httpx.AsyncClient):
    await _setup_my_profile(my)
    response = await my.get("/calendar?year=2030&month=2")
    assert response.status_code == 200
    html = response.text
    assert 'id="calendar-empty-cta"' in html
    assert 'data-action="open-event-modal"' in html
    assert 'data-date="' in html
    assert "오늘 일정 추가" in html


@pytest.mark.asyncio
async def test_jm_calendar_empty_month_cta(jm: httpx.AsyncClient):
    response = await jm.get("/calendar?year=2030&month=2")
    assert response.status_code == 200
    html = response.text
    assert 'id="calendar-empty-cta"' in html
    assert 'data-action="open-event-modal"' in html
    assert 'data-date="' in html
    assert "오늘 일정 추가" in html


@pytest.mark.parametrize("app_dir", ["my", "jm"])
def test_static_quality_slice_contracts(app_dir: str):
    app_js = (ROOT / app_dir / "static/js/app.js").read_text()
    actions_js = (ROOT / app_dir / "static/js/actions.js").read_text()
    shortcuts_js = (ROOT / app_dir / "static/shortcuts.js").read_text()
    calendar_js = (ROOT / app_dir / "static/js/calendar.js").read_text()
    dashgrid_js = (ROOT / app_dir / "static/js/dashgrid.js").read_text()
    settings_js = (ROOT / app_dir / "static/js/settings.js").read_text()
    onboarding_html = (ROOT / app_dir / "templates/partials/_onboarding.html").read_text()
    settings_html = (ROOT / app_dir / "templates/settings.html").read_text()
    css = (ROOT / app_dir / "static/css/app.css").read_text()

    assert "function updateSyncStatus" in app_js
    assert "offline" in app_js
    assert "reconnecting" in app_js
    assert "restored" in app_js
    assert "online" in app_js
    assert "window.addEventListener('offline'" in app_js
    assert "window.addEventListener('online'" in app_js
    assert "recoverStaleMainContent" in app_js
    assert "restoreStableMainContent" in app_js
    assert "htmx:historyRestore" in app_js
    assert "e.detail.target.innerHTML = '<div class=\"skeleton-page\"" not in app_js
    assert "onboarding_done" not in dashgrid_js
    assert "localStorage" not in onboarding_html
    assert "onboarding_dismissed" in onboarding_html
    assert "__plannerDashboardDelegationReady" in dashgrid_js
    assert "__plannerDashboardNeedleTimer" in dashgrid_js
    base_html = (ROOT / app_dir / "templates/base.html").read_text()
    assert 'data-action="modal-content"' in base_html
    assert "hx-history-elt" in base_html
    assert 'data-ui-theme="classic"' in base_html
    assert 'data-sidebar-style="standard"' in base_html
    assert "__PLANNER_CACHE_VERSION" in base_html
    assert "planner_cache_version" in base_html
    assert "caches.keys()" in base_html
    assert "navigator.serviceWorker.getRegistrations()" in base_html
    assert 'postMessage({type: "CLEAR_CACHE"' in base_html

    assert "window.openMemoForm" in actions_js
    assert "open-memo-form" in actions_js
    assert "modal-content" in actions_js
    assert "set-appearance-theme" in actions_js
    assert "set-sidebar-style" in actions_js
    assert "applyAppearancePreferences" in app_js
    assert "appearance_theme" in app_js
    assert "sidebar_style" in app_js
    assert "setAppearanceTheme" in settings_js
    assert "setSidebarStyle" in settings_js
    assert "appearanceThemePicker" in settings_html
    assert "sidebarStylePicker" in settings_html
    assert 'data-theme="diary"' in settings_html
    assert 'data-sidebar-style="bookmarks"' in settings_html
    assert 'src="/static/js/settings.js' in settings_html
    assert "settings-subpanel" in settings_html
    assert "settings-summary" in settings_html
    assert "settings-summary-desc" in settings_html
    assert "settings-subpanel-title\">Google 계정" in settings_html
    assert "settings-subpanel-title\">Google 캘린더" in settings_html
    assert "settings-subpanel-title\">데이터 내보내기" in settings_html
    assert "settings-export-grid" in settings_html
    assert "settings-file-input" in settings_html
    assert 'accept=".jpg,.jpeg,.png,.webp"' in settings_html

    assert "plannerQuickAction" in shortcuts_js
    assert "openMemoQuickEntry" in shortcuts_js
    assert "openEventQuickEntry" in shortcuts_js
    assert "Ctrl+Shift+M/N" in shortcuts_js
    assert "updateViaCache: 'none'" in app_js
    assert "SKIP_WAITING" in app_js

    assert "openEventModal(todayIso())" in calendar_js
    assert "event-title" in calendar_js

    sw_js = (ROOT / app_dir / "static/sw.js").read_text()
    assert f"const CACHE_NAME = '{app_dir}-planner-v6'" in sw_js
    assert "type === 'CLEAR_CACHE'" in sw_js
    assert "type === 'SKIP_WAITING'" in sw_js
    assert "caches.keys().then(keys => Promise.all(keys.map(key => caches.delete(key))))" in sw_js

    assert ".dashboard-quick-actions" in css
    assert ".sync-status-banner" in css
    assert ".empty-state-primary" in css
    assert 'body[data-ui-theme="diary"]' in css
    assert 'body[data-sidebar-style="bookmarks"]' in css
    assert ".settings-btn" in css
    assert ".settings-choice" in css
    assert ".settings-summary" in css
    assert ".settings-summary-meta" in css
    assert ".settings-subpanel" in css
    assert ".settings-export-grid" in css
    assert ".settings-file-input" in css
    assert "common-app-header" in base_html
    assert "common-app-header-row" in base_html
    assert "common-app-title-group" in base_html
    assert "common-app-header-actions" in base_html
    assert "truncate" in base_html
    assert "Common layout overlap guard" in css
    assert ".common-app-header-row" in css
    assert ".common-app-title-group" in css
    assert ".common-app-header-actions" in css
    assert ".mobile-tab-bar > div" in css
    assert "overflow-wrap: anywhere" in css
