# /goal 유동 반응형 UI — 고정 px 제거, 모든 화면 크기 대응

## 대상
/workspace/app/planners/ — My Planner (my/) base.html `<style>` 블록 리팩터링, 완료 후 JM·Work 동기화

## 문제
현재 모바일 CSS가 고정 breakpoint(640/480/380px)에 고정 px 값(44px, 52px, 13px 등)을 하드코딩.
폰 화면은 280px(Galaxy Fold 접힘)~430px(iPhone 16 Pro Max)까지 천차만별인데,
특정 기기에만 맞는 고정값은 나머지 화면에서 깨지거나 비효율적.

## 구현 항목

### A. 루트 폰트 유동화
1. 고정 breakpoint별 `html { font-size: 14px/13px }` → `clamp()` 단일 선언으로 320~460px 자연 스케일
2. 데스크탑(1024px+)은 16px 고정 유지

### B. 터치 타겟 유동화
3. `.btn-touch`, `.btn-primary`, `.btn-secondary`, `.btn-danger` 등의 `min-height: 44px` → `clamp(rem 기반 최소, vw 비례, rem 기반 최대)`
4. `.btn-icon` width/height → 동일 clamp 패턴
5. 탭바 아이템 min-height/min-width/font-size → clamp로 폰 크기 비례 스케일

### C. 카드·레이아웃 유동화
6. `.work-card` 패딩 → breakpoint 없이 `clamp()`로 항상 유동
7. `#mainContent` 좌우 패딩 → clamp로 유동
8. 리스트 간격(space-y) → 유동 rem

### D. 타이포그래피 유동화
9. 페이지 제목(h2) font-size → `clamp()`로 모바일~데스크탑 유동 스케일
10. 카드 제목(h4) → 동일 패턴
11. 부제목·날짜 등 보조 텍스트 → clamp로 최소 가독성 보장

### E. 캘린더 셀 유동화
12. breakpoint별 `min-height: 60/72/100px` → `clamp()` 단일 선언으로 전체 범위 커버

### F. 그리드 유동화
13. `@media (max-width: 480px) { grid-cols-2 → 1fr }` → `auto-fit + minmax()` 콘텐츠 기반 자동 래핑

### G. 불필요 breakpoint 정리
14. 사이즈/패딩/폰트 관련 고정값 breakpoint 제거 또는 clamp로 통합
15. 레이아웃 전환용 breakpoint만 유지 (1023px 사이드바, 1024px 탭바 숨김)

## 유지할 것
- `input { font-size: 16px !important }` — iOS 줌 방지 Apple 워커라운드, 고정 유지
- `env(safe-area-inset-*)` — 노치/다이나믹 아일랜드 대응, 기존 유지
- 색상·테마 — 이전 goal에서 완료, 변경 없음
- 기능/HTML 구조 — CSS 사이징만 변경

## 작업 방식
- my/templates/base.html `<style>` 블록의 고정값을 clamp/rem/vw로 전환
- 각 페이지 템플릿의 인라인 고정 px도 유동 단위로 수정
- My 완료 → JM·Work base.html에 동일 적용

## 검증
- Chrome DevTools 반응형 모드에서 280~500px 연속 드래그 시 깨지는 구간 없음
- iPhone SE(320px), iPhone 15(390px), iPhone 16 Pro Max(430px), Galaxy Fold(280px) 시뮬레이션 정상
- 10개 주요 페이지 200 OK
- 데스크탑(1024px+) 기존 UI 변경 없음
