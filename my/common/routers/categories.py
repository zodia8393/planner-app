"""Categories standalone page router — /categories CRUD."""

import sqlite3

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from common.utils import clamp_text, fix_mojibake

router = APIRouter()


@router.get("/categories", response_class=HTMLResponse)
async def categories_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        categories = conn.execute(
            "SELECT * FROM categories ORDER BY sort_order"
        ).fetchall()
    return S.render(request, "categories.html", {
        "page": "categories",
        "categories": [dict(r) for r in categories],
    })


@router.post("/categories", response_class=HTMLResponse)
async def create_category_page(request: Request, name: str = Form(""), color: str = Form("#d97706")):
    S = request.app.state
    pid = S.get_profile_id(request)
    name = clamp_text(fix_mojibake(name), 50)
    if name:
        with S.get_db() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order),0) FROM categories WHERE profile_id=?", (pid,)
            ).fetchone()[0]
            try:
                conn.execute(
                    "INSERT INTO categories (profile_id, name, color, sort_order) VALUES (?,?,?,?)",
                    (pid, name, color, max_order + 1),
                )
                audit_log = getattr(S, "audit_log", None)
                if audit_log:
                    audit_log(conn, "category", conn.execute("SELECT last_insert_rowid()").fetchone()[0], "create", {"name": name, "color": color})
            except sqlite3.IntegrityError:
                pass
    return S.redirect(request, "/categories")


@router.delete("/categories/{cat_id}", response_class=HTMLResponse)
async def delete_category_page(request: Request, cat_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM categories WHERE id=? AND profile_id=?", (cat_id, pid))
    if request.headers.get("HX-Request"):
        return HTMLResponse("")
    return S.redirect(request, "/categories")
