# MVP 검증 보고서

작성 시각: 2026-06-12 22:39 KST

## 검증 범위

| 인스턴스 | 선정 핵심 화면 | 핵심 흐름 |
| --- | --- | --- |
| jm | 할 일 목록 (`/todos`) | 대시보드 -> 핵심 목록 -> 항목 생성 -> 항목 수정 저장 |
| my | 할 일 목록 (`/todos`) | 대시보드 -> 핵심 목록 -> 항목 생성 -> 항목 수정 저장 |

검증 범위는 `docs/mvp_core_screens.md`를 따른다. 캘린더, 설정, 통계,
관리 및 기타 보조 화면은 전역 레이아웃이나 접근성을 차단하지 않는 한
이번 MVP 범위에서 제외한다.

## 실행 명령과 결과

| 명령 | 결과 | 비고 |
| --- | --- | --- |
| `python3 -m py_compile jm/main.py my/main.py work/main.py hub/main.py` | 통과 | 앱 진입점 문법 확인. |
| `python3 -m pytest tests/test_mvp_core_screens.py tests/test_core_todo_update_flow.py tests/test_core_todo_template_rendering.py tests/test_core_todo_desktop_responsive.py tests/test_core_todo_mobile_responsive.py tests/test_core_todo_creation_flow.py tests/test_core_todo_create_success_feedback.py tests/test_dashboard_empty_state.py tests/test_dashboard_color_contrast.py tests/test_button_accessible_names.py tests/test_mvp_input_accessible_labels.py tests/test_core_todo_keyboard_focus_order.py tests/test_dashboard_keyboard_focus_order.py -q` | `88 passed in 16.62s` | 핵심 화면 문서화, 대시보드/목록 진입, 생성/수정/저장, empty/error/status 피드백, 라벨, 대비, 키보드 접근성 확인. |
| `python3 -m pytest tests/test_dashboard_desktop_horizontal_scroll.py tests/test_dashboard_desktop_text_overlap.py tests/test_dashboard_desktop_button_containment.py tests/test_core_todo_desktop_text_overlap.py tests/test_core_todo_desktop_button_containment.py tests/test_core_todo_visual_regression.py -q` | `34 passed in 15.43s` | 데스크톱 1440x900 레이아웃, 가로 오버플로, 텍스트 겹침, 버튼 잘림 확인. |
| `python3 -m pytest tests/test_dashboard_mobile_no_horizontal_scroll.py tests/test_dashboard_mobile_text_overlap.py tests/test_dashboard_mobile_button_containment.py tests/test_core_todo_mobile_first_entry_list_responsive.py tests/test_core_todo_mobile_text_overlap.py tests/test_core_todo_creation_mobile_responsive.py tests/test_core_todo_creation_mobile_text_overlap.py tests/test_core_todo_edit_mobile_responsive.py tests/test_core_todo_edit_mobile_text_overlap.py tests/test_core_todo_creation_mobile_touch_controls.py tests/test_core_todo_edit_mobile_touch_controls.py tests/test_core_todo_mobile_action_controls.py -q` | `24 passed in 8.48s` | 모바일 390x844 레이아웃, 가로 오버플로, 텍스트 겹침, 버튼 잘림, 터치 타깃 확인. |
| `python3 -m pytest tests/test_htmx_loading_indicator_runtime.py -q` | `24 passed in 14.76s` | Playwright Chromium 기반 HTMX loading indicator, layout stability, 생성/수정 후 focus-retention runtime 확인. |

## CI 시도

타깃 검증 후 `./ci.sh`를 시작했다. 문법 확인은 완료했고 전체
`pytest tests/ -v --tb=short` 실행에서 523개 테스트를 수집했다. 보이는
출력에서는 초기 smoke 테스트 구간 통과와 live QA 서버 체크의 예상 skip이
확인됐지만, 도구 세션이 더 이상 진행 출력을 반환하지 않아 최종 exit code를
얻지 못했다. 따라서 이 보고서에서는 `./ci.sh`를 완료 통과로 보지 않고,
위의 완료된 타깃 명령들을 이번 MVP slice의 기준 검증 결과로 삼는다.

## 데이터 위생

실행한 pytest는 `tests/conftest.py`를 통해 jm/my/work 앱을 격리된 임시
SQLite 데이터베이스로 import한다. 생성된 todos/profiles도 임시
데이터베이스에만 기록된다. 이번 검증 중 실제 사용자 데이터 저장소에는
영구 테스트 항목을 남기지 않았다.

## 제외 범위와 후속 과제

이번 MVP slice에서 제외한 범위:

- 캘린더, 설정, 통계, 관리, 메모, 공지, 업무일지, 회고, 프로필 설정 및
  기타 보조 화면. 단, 전역 레이아웃, 버튼/텍스트 containment, 키보드를
  막는 접근성 문제, 명백한 모바일/데스크톱 겹침 결함은 예외적으로 최소
  수정했다.
- 인증, cloud sync, 유료 서비스, production deployment, 광범위한 정보구조
  재설계.
- jm/my 대시보드, `/todos` 목록, 생성 surface, 수정/저장 surface 및 이를
  usable하게 유지하기 위한 공유 전역 수정 범위를 넘어서는 대규모 visual
  redesign.

후속 과제:

- 중단되지 않는 세션에서 전체 `./ci.sh` 또는
  `python3 -m pytest tests/ -v --tb=short`를 최종 exit code까지 재실행한다.
- MVP 핵심 todo 흐름 승인 후 보조 화면을 화면별로 product polish한다.
- jm/my에 중복 적용된 visual 변경을 공통 design-system 계층으로 승격할지
  결정해 CSS/template drift를 줄인다.

## 잔여 위험

- 전체 `ci.sh` 실행은 이 도구 세션에서 최종 exit code를 반환하지 못했다.
  따라서 전체 CI 시도보다 완료된 타깃 MVP 검증이 더 강한 근거다.
- Ouroboros가 최종 잔여 위험 AC 기록 중 provider usage 제한으로 paused
  상태가 됐다. 구현과 타깃 검증은 완료됐지만, 내부 AC 카운터는 paused
  실행을 재개하거나 재평가하기 전까지 `12/14`로 남는다.
- 변경 범위가 mirror 구조의 `jm`과 `my` 파일 전반에 넓게 걸쳐 있으므로,
  커밋 전 unrelated dirty workspace 변경이 UI/UX slice에 섞이지 않았는지
  최종 수동 리뷰가 필요하다.
