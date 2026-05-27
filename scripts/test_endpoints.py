"""
플래너 앱 새 엔드포인트 HTTP 테스트 스크립트
대상: /timetable, /calendar?view=year
실행: python3 /workspace/app_planners/scripts/test_endpoints.py
"""

import subprocess
import sys
import time
import signal
import httpx

# ── 설정 ──
PLANNERS = [
    {
        "name": "JM",
        "dir": "/workspace/app_planners/jm",
        "port": 9001,
        "cookies": {},  # JM은 인증 불필요 (profile_id=1 고정)
    },
    {
        "name": "My",
        "dir": "/workspace/app_planners/my",
        "port": 9002,
        # planner_profile 쿠키에 기존 토큰 설정
        "cookies": {
            "planner_profile": "57be5ebaaa4e4f6e9c58c7408cb6e665e6c44607b39f4299841366dbfdba6ca2"
        },
    },
    {
        "name": "Work",
        "dir": "/workspace/app_planners/work",
        "port": 9003,
        # work_profile 쿠키에 profile_id 설정 (PIN 없음)
        "cookies": {"work_profile": "1"},
    },
]

ENDPOINTS = [
    ("/timetable", "기본 타임테이블"),
    ("/timetable?dt=2026-01-01", "날짜 지정"),
    ("/timetable?dt=2026-02-29", "윤년 아닌 날짜"),
    ("/timetable?dt=invalid", "잘못된 날짜"),
    ("/calendar?view=year", "연간 캘린더"),
    ("/calendar?view=year&year=2026", "연간 캘린더 2026"),
    ("/calendar?view=year&year=2025", "연간 캘린더 과거연도"),
]

STARTUP_TIMEOUT = 15  # 서버 시작 대기 최대 초
REQUEST_TIMEOUT = 10  # HTTP 요청 타임아웃 초


def wait_for_server(port: int, timeout: int = STARTUP_TIMEOUT) -> bool:
    """서버가 응답할 때까지 대기. 성공 시 True."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2)
            if r.status_code < 500:
                return True
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        # /health가 없을 수 있으므로 / 도 시도
        try:
            r = httpx.get(
                f"http://127.0.0.1:{port}/",
                timeout=2,
                follow_redirects=False,
            )
            if r.status_code < 500:
                return True
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        time.sleep(0.5)
    return False


def test_endpoint(
    port: int, path: str, cookies: dict
) -> dict:
    """단일 엔드포인트 테스트. 결과 dict 반환."""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        r = httpx.get(
            url,
            cookies=cookies,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=False,
        )
        body = r.text
        has_html = "<html" in body.lower() or "<!doctype" in body.lower()
        return {
            "status": r.status_code,
            "size": len(body),
            "has_html": has_html,
            "redirect": r.headers.get("location", ""),
            "error": "",
        }
    except Exception as e:
        return {
            "status": 0,
            "size": 0,
            "has_html": False,
            "redirect": "",
            "error": str(e),
        }


def main():
    results = {}  # {planner_name: [{endpoint, desc, ...}, ...]}

    for planner in PLANNERS:
        name = planner["name"]
        port = planner["port"]
        app_dir = planner["dir"]
        cookies = planner["cookies"]

        print(f"\n{'='*60}")
        print(f"  {name} 플래너 (port {port})")
        print(f"{'='*60}")

        # 1. uvicorn 서버 시작
        print(f"  서버 시작 중... ({app_dir})")
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "main:app",
                "--host", "127.0.0.1",
                "--port", str(port),
                "--log-level", "warning",
            ],
            cwd=app_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # 2. 서버 응답 대기
        if not wait_for_server(port):
            print(f"  [FAIL] 서버 시작 실패 (timeout {STARTUP_TIMEOUT}s)")
            # stderr 출력
            proc.terminate()
            proc.wait(timeout=5)
            stderr_out = proc.stderr.read().decode(errors="replace")
            if stderr_out:
                print(f"  stderr: {stderr_out[:500]}")
            results[name] = [
                {
                    "endpoint": ep,
                    "desc": desc,
                    "status": 0,
                    "size": 0,
                    "has_html": False,
                    "redirect": "",
                    "error": "서버 시작 실패",
                }
                for ep, desc in ENDPOINTS
            ]
            continue

        print(f"  서버 준비 완료")

        # 3. 엔드포인트 테스트
        planner_results = []
        for path, desc in ENDPOINTS:
            result = test_endpoint(port, path, cookies)
            result["endpoint"] = path
            result["desc"] = desc
            planner_results.append(result)

            status = result["status"]
            size = result["size"]
            err = result["error"]
            redir = result["redirect"]

            if err:
                mark = "FAIL"
            elif status == 200:
                mark = "OK"
            elif 300 <= status < 400:
                mark = f"REDIRECT -> {redir}"
            else:
                mark = f"HTTP {status}"

            print(f"  [{mark:>6s}] {path:<45s} | {status} | {size:>6d}B | {desc}")

        results[name] = planner_results

        # 4. 서버 종료
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        print(f"  서버 종료 완료")

    # ── 종합 보고 ──
    print(f"\n\n{'='*80}")
    print(f"  종합 결과 요약")
    print(f"{'='*80}")
    print(f"{'플래너':<8s} {'엔드포인트':<45s} {'상태':>4s} {'크기':>8s} {'HTML':>4s} {'결과':<12s}")
    print("-" * 90)

    total = 0
    ok_count = 0
    fail_count = 0

    for planner_name, planner_results in results.items():
        for r in planner_results:
            total += 1
            status = r["status"]
            if status == 200:
                ok_count += 1
                verdict = "PASS"
            elif 300 <= status < 400:
                ok_count += 1
                verdict = f"REDIRECT"
            elif r["error"]:
                fail_count += 1
                verdict = "FAIL"
            else:
                fail_count += 1
                verdict = f"HTTP {status}"

            print(
                f"{planner_name:<8s} {r['endpoint']:<45s} "
                f"{status:>4d} {r['size']:>7d}B "
                f"{'Y' if r['has_html'] else 'N':>4s} "
                f"{verdict:<12s}"
            )

    print("-" * 90)
    print(f"총 {total}건: PASS {ok_count} / FAIL {fail_count}")
    print()

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
