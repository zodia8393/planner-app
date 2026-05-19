"""Common routers shared across planner apps.

Each app injects dependencies via app.state before including these routers:
    app.state.get_db          — () -> contextmanager[Connection]
    app.state.get_profile_id  — (Request) -> int
    app.state.get_profile_name — (Request) -> str
    app.state.render          — (Request, template, context) -> Response
    app.state.redirect        — (Request, url) -> Response
    app.state.templates       — Jinja2Templates
    app.state.audit_log       — (conn, entity_type, entity_id, action, changes, profile_id?) -> None
    app.state.event_bus       — EventBus (broadcast + emit for SSE)
    app.state.get_categories  — (conn, pid) -> list[Row]
"""
