# /goal 모바일 UI 검수 + UX 최적화 — 라이브 URL 크롤링 + 모바일 전용 개선

## 대상
- JM: https://hj-jm-planner.fly.dev (인증 없이 접근 가능)
- 소스: /workspace/app_planners/my/templates/ (기준 코드)

## 목적
1단계: 배포 페이지를 모바일 UA로 fetch → HTML 분석 → 잔존 문제 검출·수정
2단계: 모바일 환경 전용 UX 최적화 구현

## 검수 대상 페이지 (10개)
1. `/` (대시보드)
2. `/todos` (할일)
3. `/calendar` (캘린더)
4. `/today` (오늘)
5. `/habits` (습관)
6. `/worklogs` (업무일지)
7. `/memos` (메모)
8. `/settings` (설정)
9. `/forms` (양식)
10. `/automations` (자동화)

## 검수 방법
각 페이지에 대해:
1. `curl -s -A "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1" URL` 로 HTML 가져오기
2. 가져온 HTML에서 아래 항목 자동 검출

---

## Part 1: 잔존 문제 검수 (A~H)

### A. 터치 타겟 미달
- `btn-primary`, `btn-secondary`, `btn-sm`, `btn-icon` 없이 `py-1` 이하인 버튼
- `px-2 py-1`, `px-2.5 py-1` 등 24~28px 높이 버튼 잔존

### B. 체크박스·라디오
- flex 컨테이너 안 세로 늘어남 구조 잔존
- `align-self: center` / `self-center` 미적용

### C. 폼 입력 높이 불일치
- input/select의 py가 `py-2.5` 미만
- input/select에 `text-xs` (16px 미만 → iOS 줌)

### D. 버튼 크기 불일치
- 3종(primary/secondary/sm) 외 패턴 잔존
- 인라인 `px-N py-N` 직접 사이즈 지정

### E. 고정 px 잔존
- `w-10 h-10`, `w-7 h-7` 등 clamp 미전환
- `style="width: Npx"` 인라인 고정

### F. 간격 불일치
- 같은 용도에서 gap-1/1.5/2/3 혼재
- 버튼 간 `gap-1` 이하 (오터치 위험)

### G. 텍스트 가시성
- 다크모드에서 `text-slate-400` 이하 명도 본문/라벨
- `text-[10px]`, `text-[9px]` 극소 텍스트

### H. 레이아웃 오버플로
- `flex-nowrap` + 고정 너비 = 가로 스크롤
- 긴 텍스트에 `truncate`/`overflow-hidden` 누락

---

## Part 2: 모바일 UX 최적화 (I~R)

### I. 모달 → 바텀시트 전환
- 화면 중앙 팝업 모달은 엄지 닿기 어려움
- 모바일(≤768px)에서 모달을 하단에서 슬라이드업하는 바텀시트로 전환
- `transform: translateY(100%)` → `translateY(0)` 애니메이션
- 대상: 할일 추가, 일정 추가/편집, 메모 작성, 양식 선택 등 모든 모달

### J. 스티키 헤더
- 긴 리스트 스크롤 시 페이지 제목+주요 액션 버튼이 사라짐
- 페이지 헤더(제목+추가 버튼)를 `position: sticky; top: 0; z-index: 10` 처리
- 스크롤 시 헤더에 `backdrop-filter: blur` + 반투명 배경
- 대상: todos, memos, worklogs, habits, calendar

### K. 스와이프 제스처
- 리스트 아이템을 좌→우 스와이프하면 완료 처리
- 우→좌 스와이프하면 삭제 확인
- CSS `overflow-x: auto` + JS `touchstart/touchmove/touchend`
- 대상: todo 아이템, 습관 아이템

### L. 풀-투-리프레시
- 모바일에서 목록 페이지 당겨서 새로고침 (네이티브 앱 느낌)
- `overscroll-behavior-y: contain` + JS 터치 이벤트
- 대상: 대시보드, todos, memos, worklogs

### M. 스켈레톤 로딩
- HTMX 요청 중 빈 화면 대신 스켈레톤 플레이스홀더 표시
- `.skeleton` 클래스: `background: linear-gradient(90deg, var(--color-surface) 25%, var(--color-border) 50%, var(--color-surface) 75%)` + `animation: shimmer`
- 대상: 대시보드 위젯, 리스트 로딩

### N. 엄지존 최적화 (Thumb Zone)
- 주요 액션(추가 버튼, 네비게이션)을 화면 하단 50%에 배치
- FAB(플로팅 추가 버튼)을 `bottom: calc(env(safe-area-inset-bottom) + 탭바높이 + 1rem)` 위치
- 필터/정렬은 상단, 추가/완료 액션은 하단

### O. 키보드 대응
- input focus 시 `scroll-padding-bottom`으로 키보드에 가려지지 않게
- `visualViewport` API로 키보드 높이 감지 → FAB/탭바 위치 조정
- 모달/바텀시트 내 input focus 시 시트 높이 자동 조절

### P. 수평 스크롤 스냅
- 카테고리 탭, 날짜 필터 등 가로 스크롤 영역에 `scroll-snap-type: x mandatory`
- 각 아이템에 `scroll-snap-align: start`
- 스크롤 위치 표시 인디케이터 (그라데이션 페이드 or 도트)
- 대상: 카테고리 필터, 캘린더 주간 뷰, 습관 30일 히트맵

### Q. 터치 피드백 강화
- 리스트 아이템 탭 시 `active:bg-slate-50 dark:active:bg-slate-800/50` + 미세 스케일
- 삭제/위험 액션 시 `haptic feedback` (navigator.vibrate(50)) 
- 완료 체크 시 짧은 진동 + confetti (기존 confetti 활용)
- 길게 누르기(long-press) → 컨텍스트 메뉴 (편집/삭제/이동)

### R. 오버스크롤·바운스 제어
- `overscroll-behavior: none` 으로 페이지 바운스 방지 (PWA 네이티브 느낌)
- 모달/바텀시트 열린 상태에서 배경 스크롤 잠금 (`body { overflow: hidden }`)
- iOS rubber-band 효과 제어

---

## 작업 순서
1. Part 1 (A~H) 검수 → 잔존 문제 수정
2. Part 2 (I~R) 중 CSS-only 항목 먼저 (J, M, P, R)
3. Part 2 중 JS 필요 항목 (I, K, L, N, O, Q)
4. My 완료 → JM·Work 동기화

## 산출물
1. **Part 1 검수 결과표**: 페이지별 문제 유형·건수, 수정 완료 여부
2. **Part 2 적용 결과표**: 항목별 적용 페이지·구현 방식
3. 수정 완료 후 → JM·Work 동기화

## 하지 말 것
- 기능 로직 변경 (CSS/JS UX 레이어만)
- 백엔드 API 변경
- 색상·테마 변경 (이전 goal에서 완료)
- 데스크탑(1024px+) UI 변경
