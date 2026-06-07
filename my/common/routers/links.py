"""Links router — /links CRUD."""

from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from common.utils import clamp_text, fix_mojibake

router = APIRouter()


@router.get("/links", response_class=HTMLResponse)
async def links_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM links WHERE profile_id=? ORDER BY created_at DESC", (pid,)
        ).fetchall()
        cats = conn.execute(
            "SELECT DISTINCT category FROM links WHERE profile_id=? AND category != '' ORDER BY category",
            (pid,),
        ).fetchall()
    links = [dict(r) for r in rows]
    categories = [r["category"] for r in cats]
    # Read tunnel data for cross-planner links
    tunnel_data = None
    tunnel_file = S.base_dir / "tunnel-url.txt"
    if tunnel_file.exists():
        try:
            import json
            text = tunnel_file.read_text().strip()
            if text.startswith("{"):
                tunnel_data = json.loads(text)
            else:
                tunnel_data = {"jm": {"url": text}}
        except Exception:
            pass
    current_app = getattr(S, "app_name", "planner").split("-")[0]
    return S.render(request, "links.html", {
        "page": "links",
        "links": links,
        "link_categories": categories,
        "tunnel_data": tunnel_data,
        "current_app": current_app,
    })


@router.post("/links", response_class=HTMLResponse)
async def create_link(request: Request, title: str = Form(""), url: str = Form(""),
                      category: str = Form(""), description: str = Form("")):
    S = request.app.state
    pid = S.get_profile_id(request)
    if not title or not url:
        return S.redirect(request, "/links")
    if not url.startswith(('http://', 'https://', '/')):
        return S.redirect(request, "/links")
    with S.get_db() as conn:
        conn.execute(
            "INSERT INTO links (profile_id, title, url, category, description) VALUES (?,?,?,?,?)",
            (pid, title, url, category, description),
        )
    return S.redirect(request, "/links")


@router.delete("/links/{link_id}", response_class=HTMLResponse)
async def delete_link(request: Request, link_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM links WHERE id=? AND profile_id=?", (link_id, pid))
    return HTMLResponse("")
