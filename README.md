# Planner 웹앱 (Flask/FastAPI, 3개 인스턴스 + Hub)

## 목적

개인/공유/업무용 플래너 웹 애플리케이션. 할일 관리, 캘린더, 업무일지, 집중 모드(Pomodoro), 양식 빌더, 자동화 규칙, 통계/리뷰 등 종합 생산성 도구를 제공한다. 3개의 독립 인스턴스(JM/My/Work)와 통합 대시보드(Hub)로 구성된다.

## 기간

2025년 5월 ~ 진행중 (개인 프로젝트)

## 주요 기능

- **할일 관리**: CRUD, 우선순위/카테고리/태그/마감일, 에너지 레벨 필터, 일괄 작업, 서브태스크
- **캘린더**: 월/주 캘린더, 이벤트 관리, 반복 일정 (일/주/월/연 + 예외일)
- **업무일지**: 일별 업무 기록, 카테고리별 시간 입력, 이미지 첨부
- **집중 모드**: Pomodoro 타이머 (25/45/60분 프리셋), 업무일지 자동 기록
- **시간 예산**: 카테고리별 주간 목표 시간 설정 및 진행률 추적
- **양식 빌더**: 커스텀 폼 생성 (품의서/회의록/업무일지 프리셋)
- **자동화**: 규칙 기반 할일 자동 생성 (매일/매주/매월 트리거)
- **통계/리뷰**: 완료 추이, 카테고리별 분포, 365일 히트맵, 주간/월간 리뷰
- **Hub 대시보드**: JM/My/Work 3개 플래너 통합 현황 (5분 자동갱신)
- **SSE 실시간 동기화**: 멀티 디바이스 실시간 갱신
- **PWA**: Service Worker + manifest.json, 오프라인 캐시 지원
- **감사 로그**: 할일 변경 이력 추적

## 디렉토리 구조

```
/workspace/app_planners/
├── common/                    # 공용 모듈 (모든 인스턴스 공유)
│   ├── __init__.py
│   ├── constants.py           # 상수 정의
│   ├── db.py                  # SQLite 연결 (WAL mode)
│   ├── excel.py               # 엑셀 내보내기
│   ├── filters.py             # Jinja2 필터
│   ├── gcal.py                # Google Calendar 연동
│   ├── holidays.py            # 한국 공휴일
│   ├── image.py               # 이미지 처리
│   ├── middleware.py           # 인증/프로필 미들웨어
│   ├── nlp_date.py            # 자연어 날짜 파싱 (한국어)
│   ├── recurrence.py          # 반복 일정 엔진
│   ├── search.py              # 전체 검색
│   ├── stats.py               # 통계 집계
│   ├── utils.py               # 유틸리티
│   ├── routers/               # FastAPI 라우터
│   │   ├── events.py          # 캘린더 이벤트
│   │   ├── forms.py           # 양식 빌더
│   │   ├── memos.py           # 메모
│   │   ├── misc.py            # 기타 (감사로그, D-day 등)
│   │   ├── notices.py         # 공지사항
│   │   ├── settings.py        # 설정
│   │   ├── sse.py             # SSE 실시간 동기화
│   │   ├── todos.py           # 할일
│   │   └── worklogs.py        # 업무일지
│   ├── static/                # 공용 정적 파일
│   └── templates/             # 공용 Jinja2 템플릿
├── jm/                        # JM 인스턴스 (공유 플래너)
│   ├── main.py                # FastAPI 앱 엔트리포인트 (71K)
│   ├── Dockerfile
│   ├── fly.toml               # Fly.io 배포 설정
│   ├── data/                  # SQLite DB
│   ├── static/                # 정적 파일 (tailwind.css)
│   └── templates/             # Jinja2 템플릿
├── my/                        # My 인스턴스 (개인 플래너, 프로덕션)
│   ├── main.py                # FastAPI 앱 엔트리포인트 (83K)
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── fly.toml               # Fly.io 배포 설정
│   ├── data/                  # SQLite DB
│   ├── static/
│   └── templates/
├── work/                      # Work 인스턴스 (업무 플래너, 사내 LAN)
│   ├── main.py                # FastAPI 앱 엔트리포인트 (81K)
│   ├── Dockerfile
│   ├── fly.toml
│   ├── cert.pem / key.pem    # HTTPS 자체서명 인증서
│   ├── data/
│   ├── static/
│   └── templates/
├── hub/                       # 통합 대시보드 (읽기 전용)
│   ├── main.py                # 대시보드 앱 (8K)
│   ├── Dockerfile
│   ├── fly.toml
│   ├── data/links.json
│   └── templates/
├── tests/                     # pytest 테스트
│   ├── conftest.py            # 공용 Fixture
│   ├── smoke_test.py          # 스모크 테스트
│   ├── crud_test.py           # CRUD 테스트
│   ├── nlp_date_test.py       # 자연어 날짜 파싱 테스트
│   ├── p2_test.py             # Phase 2 테스트
│   └── production_qa_test.py  # 프로덕션 QA 테스트 (33K)
├── docs/                      # 문서
├── deploy.sh                  # Fly.io 배포 스크립트
├── ci.sh                      # CI 스크립트 (구문검증 + pytest)
├── start-work.sh              # Work 인스턴스 로컬 실행
├── tailwind.config.js         # Tailwind CSS 설정
├── input.css                  # Tailwind 입력 CSS
├── .env -> /workspace/.env    # 환경변수 심볼릭 링크
├── .gitignore
├── USAGE.md                   # 사용자 가이드
└── .git/
```

## 주요 스크립트

| 파일 | 기능 |
|------|------|
| `jm/main.py` | JM 플래너 FastAPI 앱 (공유, 프로필 선택) |
| `my/main.py` | My 플래너 FastAPI 앱 (개인, 프로덕션) |
| `work/main.py` | Work 플래너 FastAPI 앱 (업무, LAN HTTPS) |
| `hub/main.py` | Hub 통합 대시보드 |
| `common/nlp_date.py` | 한국어 자연어 날짜 파싱 ("다음주 월요일", "3일 후" 등) |
| `common/recurrence.py` | 반복 일정 엔진 (일/주/월/연 + 예외일) |
| `common/routers/todos.py` | 할일 CRUD + 에너지 레벨 + 일괄작업 라우터 |
| `common/routers/worklogs.py` | 업무일지 라우터 |
| `deploy.sh` | Fly.io 배포 (Tailwind 빌드 + common 복사 + flyctl deploy) |
| `ci.sh` | CI (py_compile 구문검증 + pytest) |
| `start-work.sh` | Work 인스턴스 로컬 HTTPS 시작 |

## 데이터 위치

- JM DB: `jm/data/` (Fly.io 볼륨 /data)
- My DB: `my/data/` (Fly.io 볼륨 /data)
- Work DB: `work/data/` (로컬)
- Hub 링크: `hub/data/links.json`

## 모델 파일

N/A

## 실행 방법

```bash
# 의존성 설치
pip install fastapi uvicorn[standard] jinja2 python-multipart markupsafe httpx

# JM/My -- Fly.io 배포
cd /workspace/app_planners
bash deploy.sh jm       # 또는 my
# --skip-tests 옵션으로 테스트 건너뛰기 가능

# Work -- 로컬 (HTTPS)
bash start-work.sh
# 또는 수동:
cd work && python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 \
    --ssl-keyfile=key.pem --ssl-certfile=cert.pem

# Hub -- 로컬
cd hub && python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# 테스트
cd /workspace/app_planners
python3 -m pytest tests/ -v

# CI
bash ci.sh
```

### 접속 URL

| 앱 | URL | 인증 |
|----|-----|------|
| JM | https://jm-planner.fly.dev | 프로필 선택 (PIN 가능) |
| My | https://my-planner.fly.dev | 프로필 생성 후 자동 로그인 |
| Work | https://192.168.0.29:8001 | 프로필 선택 + PIN |
| Hub | http://localhost:8000 | 없음 (읽기 전용) |

## 의존성

```
fastapi
uvicorn[standard]
jinja2
python-multipart
markupsafe
httpx
```

프론트엔드: HTMX + Tailwind CSS 3.4.17 (빌드) + Chart.js + Sortable.js

## TODO

- [ ] Google Calendar 연동 완료
- [ ] 모바일 PWA 오프라인 동기화 개선
- [ ] 공용 모듈 common/ 리팩터링 (main.py 크기 축소)
