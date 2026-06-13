# /goal 모바일 UI 일관성 & 가시성 전면 개선

## 대상
/workspace/app/planners/ — My Planner (my/), 완료 후 JM·Work 동기화

## 문제
모바일(≤640px)에서 버튼 크기 중구난방, 텍스트 가시성 떨어짐, 터치 타겟 불균일.
Play Store 런칭 전 모바일 퍼스트 품질로 올려야 함.

## 구현 항목 (우선순위순)

### A. 터치 타겟 통일 (최소 44×44px, Apple HIG 기준)
1. 모든 버튼·링크의 `min-height: 44px` 보장 — base.html에 글로벌 CSS 클래스 `.btn-touch` 정의
2. 아이콘 버튼 (삭제, 편집, 토글 등) → `w-10 h-10` 이상으로 통일
3. 네비게이션 탭바 아이템 → 터치 영역 `py-3` 이상
4. 폼 input/select → `min-height: 44px`, `text-base` (16px, iOS 줌 방지)
5. 체크박스·라디오 → 커스텀 스타일로 44px 터치 영역

### B. 버튼 크기·스타일 통일
6. 프라이머리 버튼: `px-4 py-3 text-sm font-semibold rounded-xl` 통일
7. 세컨더리 버튼: `px-3 py-2.5 text-sm font-medium rounded-lg border` 통일
8. 위험(삭제) 버튼: 빨간 계열, 크기는 프라이머리와 동일
9. FAB (플로팅 추가 버튼): `w-14 h-14 rounded-full shadow-lg` 통일
10. 버튼 간 간격: `gap-3` 이상 (오터치 방지)

### C. 타이포그래피 가시성
11. 페이지 제목: `text-xl font-bold` (모바일), 데스크탑 `text-2xl`
12. 카드 내 제목: `text-base font-semibold` → 현재 `text-sm`인 곳 상향
13. 부가 텍스트 (날짜, 카테고리): `text-xs` 유지하되 `text-slate-500` → `text-slate-600` (명도 상향)
14. 빈 상태 메시지: `text-sm text-slate-500` → `text-base text-slate-600`
15. 입력 placeholder: `text-slate-400` → `text-slate-500` (대비 강화)

### D. 카드·레이아웃 모바일 최적화
16. 카드 패딩: 모바일 `p-4` (현재 `p-6`인 곳 축소하여 콘텐츠 영역 확보)
17. 페이지 좌우 마진: 모바일 `px-4` 통일 (현재 `px-6`인 곳)
18. 리스트 아이템 간격: `gap-2` → `gap-3` (구분 명확화)
19. 카드 내 액션 버튼 우측 정렬: `ml-auto flex-shrink-0`

### E. 색상 대비·다크모드 가시성
20. 비활성 텍스트 대비: WCAG AA 기준 4.5:1 이상
21. 액센트 컬러 on-white: 인디고 `#4f46e5` → 대비 확인
22. 다크모드 카드 배경 vs 텍스트: 명확한 구분 확인
23. 상태 뱃지 (완료/진행중/지연): 색상+아이콘 이중 인코딩

### F. 인터랙션 피드백
24. 버튼 press 피드백: `active:scale-95 transition-transform` 추가
25. 리스트 아이템 스와이프/탭: `active:bg-slate-50 dark:active:bg-slate-700/50`
26. 로딩 상태: 폼 제출 시 버튼 `opacity-50 pointer-events-none` + 스피너

## 작업 방식
- base.html의 `<style>` 블록에 모바일 공통 CSS 먼저 정의
- 각 페이지 템플릿을 순회하며 클래스 적용
- 변경 전후 비교: `curl` 200 OK + 주요 페이지 10개 확인
- My 완료 → JM·Work에 동일 변경 동기화

## 검증
- 모든 버튼/링크 터치 타겟 ≥ 44px
- input 16px 이상 (iOS 줌 안 일어남)
- 텍스트 대비 WCAG AA 충족
- 다크모드에서도 동일 가시성
- 페이지 10개 200 OK
