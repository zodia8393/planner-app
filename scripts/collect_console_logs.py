#!/usr/bin/env python3
"""Playwright로 모든 플래너 페이지를 순회하며 브라우저 콘솔 로그를 수집."""

import json
import sys
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

PLANNERS = {
    "JM": "https://hj-jm-planner.fly.dev",
    "My": "https://hj-my-planner.fly.dev",
}

ROUTES = [
    "/", "/todos", "/todos/kanban", "/calendar", "/today", "/habits",
    "/worklogs", "/memos", "/forms", "/notices", "/ddays", "/links",
    "/stats", "/review", "/search", "/settings", "/todo-templates",
    "/automations", "/categories", "/audit-log", "/plans",
]

EXTRA_ROUTES = {
    "My": ["/files"],
}

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


def collect(planner_name: str, base_url: str, browser, routes=None):
    results = []
    for route in (routes or ROUTES):
        url = f"{base_url}{route}"
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        messages = []
        page.on("console", lambda msg, _m=messages: _m.append({
            "type": msg.type,
            "text": msg.text,
            "location": str(msg.location) if hasattr(msg, "location") else "",
        }))

        errors = []
        page.on("pageerror", lambda err, _e=errors: _e.append(str(err)))

        try:
            resp = page.goto(url, wait_until="load", timeout=15000)
            page.wait_for_timeout(2000)
            status = resp.status if resp else 0
        except Exception as e:
            status = 0
            errors.append(f"Navigation error: {e}")

        results.append({
            "planner": planner_name,
            "route": route,
            "url": url,
            "status": status,
            "console": messages,
            "errors": errors,
        })
        page.close()
    return results


def main():
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")

    all_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, url in PLANNERS.items():
            routes = ROUTES + EXTRA_ROUTES.get(name, [])
            print(f"[{name}] {url} — {len(routes)} pages...")
            results = collect(name, url, browser, routes)
            all_results.extend(results)
        browser.close()

    # JSON log
    log_path = LOG_DIR / f"console_{timestamp}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"collected_at": date_str, "results": all_results}, f, ensure_ascii=False, indent=2)

    # Summary
    total_errors = sum(len(r["errors"]) for r in all_results)
    total_console = sum(len(r["console"]) for r in all_results)
    warn_count = sum(1 for r in all_results for m in r["console"] if m["type"] == "warning")
    error_console = sum(1 for r in all_results for m in r["console"] if m["type"] == "error")
    non_200 = [r for r in all_results if r["status"] != 200]

    print(f"\n{'='*60}")
    print(f"  Console Log Collection — {date_str}")
    print(f"{'='*60}")
    print(f"  Pages scanned : {len(all_results)}")
    print(f"  Console msgs  : {total_console} (warn: {warn_count}, error: {error_console})")
    print(f"  Page errors   : {total_errors}")
    print(f"  Non-200 routes: {len(non_200)}")
    if non_200:
        for r in non_200:
            print(f"    {r['planner']} {r['route']} → {r['status']}")

    if error_console > 0 or total_errors > 0:
        print(f"\n  ⚠ Issues found:")
        for r in all_results:
            for e in r["errors"]:
                print(f"    [{r['planner']}] {r['route']} PAGE_ERROR: {e[:120]}")
            for m in r["console"]:
                if m["type"] == "error":
                    print(f"    [{r['planner']}] {r['route']} CONSOLE_ERROR: {m['text'][:120]}")

    print(f"\n  Log saved: {log_path}")
    print(f"{'='*60}")

    # Rotate: keep last 30 logs
    logs = sorted(LOG_DIR.glob("console_*.json"))
    if len(logs) > 30:
        for old in logs[:-30]:
            old.unlink()
            print(f"  Rotated: {old.name}")

    return 1 if (total_errors > 0 or error_console > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
