from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _asset(app_name: str, relative_path: str) -> str:
    return (ROOT / app_name / relative_path).read_text(encoding="utf-8")


def test_jm_my_todo_create_submit_and_cancel_focus_controls_are_distinct():
    for app_name in ("jm", "my"):
        template = _asset(app_name, "templates/todos.html")
        css = _asset(app_name, "static/css/app.css")

        assert 'type="submit" class="todo-create-submit btn-accent' in template
        assert 'type="reset" class="todo-create-cancel' in template
        assert 'aria-label="할일 추가 취소"' in template
        assert "#todoPage #addForm .todo-create-submit:focus-visible" in css
        assert "#todoPage #addForm .todo-create-cancel:focus-visible" in css
        assert "box-shadow: 0 0 0 5px var(--color-accent-soft), var(--shadow-btn-accent);" in css
        assert "outline: 3px solid var(--color-text-muted);" in css
        assert "box-shadow: 0 0 0 5px rgba(87, 83, 78, 0.18);" in css
