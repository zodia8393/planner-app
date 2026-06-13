# /goal 모바일 UI 일괄 정리 — 실제 스크린샷 기반 문제 해결

## 대상
/workspace/app/planners/my/templates/ 전체 템플릿, 완료 후 JM·Work 동기화

## 문제
모바일 실기기 스크린샷 검수 결과, 버튼·입력·체크박스 크기가 페이지마다 다르고 터치 타겟 미달·세로 늘어남 등 가시성·조작성 문제 다수 발견.
base.html에 clamp 기반 디자인 토큰(btn-primary 등)을 정의했으나, 개별 템플릿에서 인라인 클래스(px-2 py-1 text-xs 등)로 덮어쓰고 있어 실제 적용이 안 됨.

## 구현 항목

### A. 체크박스·라디오 세로 늘어남 수정
- **원인**: base.html의 `label:has(input[type="checkbox"])` 에 min-height clamp가 적용되면서 체크박스 자체도 세로로 늘어남
- **수정**: 체크박스·라디오에 `align-self: center; max-height: 1.25rem` 추가하여 부모 높이와 무관하게 정사각 유지
- **파일**: base.html CSS + settings.html(라디오), dashboard.html(체크박스), todos.html(요일 체크박스)

### B. 버튼 크기 통일 — 인라인 클래스 → 디자인 토큰 전환
현재 6종 이상 버튼 패턴이 혼재:
- `px-2 py-1 text-xs` (~24px) — 서브태스크 추가 등
- `px-2.5 py-1 text-xs` (~28px) — 에너지 필터 등
- `px-3 py-1.5 text-xs` (~30px) — 태그 필터 등
- `px-3 py-2 text-sm` (~36px) — 일부 폼 버튼
- `px-4 py-2.5 text-sm` (~40px) — 설정 버튼
- `btn-primary` (clamp 44~48px) — 일부만 적용

**통일 기준 3종으로 축소:**
- `.btn-primary` — 주요 액션 (추가, 저장, 제출)
- `.btn-secondary` — 보조 액션 (필터, 토글, 취소)
- `.btn-sm` (신규) — 인라인 소형 버튼 (태그, 퀵버튼, 에너지레벨). 단 min-height clamp(2rem, 1.5rem+2vw, 2.5rem) 이상 보장

**수정 대상 파일:**
- todos.html: 필터 버튼 8개, 에너지 버튼 3개, 반복 설정 버튼, 일괄선택 버튼
- partials/todo_item.html: 서브태스크 추가 버튼
- worklogs.html: 시간 퀵버튼(0.5h, 1h 등)
- dashboard.html: 집중모드 퀵스타트 버튼
- settings.html: 폰트 크기·테마 색상 버튼
- forms.html: 액션 버튼
- calendar.html: 모달 버튼

### C. 폼 입력 높이 통일
현재 `py-1`(~28px) ~ `py-2.5`(~40px) 혼재.
- **모든 input/select**: base.html의 clamp min-height가 적용되도록 인라인 py 값 통일 → `py-2.5 text-sm`
- **textarea**: min-height 별도 (내용 영역이므로 터치 타겟과 다름)
- **수정 대상**: todos.html(날짜·우선순위·카테고리·에너지·태그 7개 input), worklogs.html(제목·시간 2개), memos.html(제목 1개)

### D. 간격·패딩 통일
- 필터 영역 `gap-1.5` → `gap-2` 통일
- 폼 요소 간 `gap-2` → `gap-3` 통일 (오터치 방지)
- 카드 내 액션 버튼 영역 하단 `mt-3` 통일

### E. 고정 px 위젯 유동화
- 대시보드 이모지 박스 `w-10 h-10` → clamp
- 캘린더 날짜 원 `w-7 h-7` → clamp
- 설정 색상 버튼 `w-10 h-10` → clamp
- 습관 색상 피커 `w-10 h-9` → clamp

## 작업 방식
- base.html `<style>`에 `.btn-sm` 클래스 추가 + 체크박스 fix
- 각 템플릿 순회하며 인라인 버튼·입력 클래스를 디자인 토큰으로 교체
- My 전체 완료 → JM·Work base.html + 변경된 템플릿 동기화

## 하지 말 것
- 기능·로직 변경 (CSS 클래스만)
- 색상·테마 변경 (이전 goal에서 완료)
- 데스크탑(1024px+) UI 변경
- HTML 구조 변경 (클래스 속성만 교체)

## 검증
- 체크박스·라디오가 정사각형 유지되는지 확인
- 모든 버튼 min-height ≥ 2rem (32px) 이상
- 모든 input/select min-height ≥ 2.5rem (40px) 이상
- 280~430px 범위에서 깨지는 구간 없음
- 10개 주요 페이지 200 OK
- My/JM/Work 동기화 완료
