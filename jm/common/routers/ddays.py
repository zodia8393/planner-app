"""D-day router — /ddays CRUD."""

from datetime import datetime, date

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from common.utils import clamp_text, fix_mojibake, validate_date_str

router = APIRouter()


def _calc_dday(target_date_str: str) -> int:
    try:
        target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        return (target - date.today()).days
    except (ValueError, TypeError):
        return 0


@router.get("/ddays", response_class=HTMLResponse)
async def ddays_page(request: Request):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM ddays WHERE profile_id=? ORDER BY target_date ASC", (pid,)
        ).fetchall()
    ddays = []
    for r in rows:
        d = dict(r)
        d["dday"] = _calc_dday(d["target_date"])
        if not d.get("icon"):
            d["icon"] = "\U0001f3af"
        ddays.append(d)
    return S.render(request, "ddays.html", {"page": "ddays", "ddays": ddays})


@router.post("/ddays", response_class=HTMLResponse)
async def create_dday(request: Request, title: str = Form(""), target_date: str = Form(""), icon: str = Form("\U0001f3af")):
    S = request.app.state
    pid = S.get_profile_id(request)
    title = clamp_text(fix_mojibake(title), 100).strip()
    target_date = validate_date_str(target_date)
    if not title or not target_date:
        return S.redirect(request, "/ddays")
    with S.get_db() as conn:
        conn.execute(
            "INSERT INTO ddays (profile_id, title, target_date, icon) VALUES (?,?,?,?)",
            (pid, title, target_date, icon or "\U0001f3af"),
        )
    return S.redirect(request, "/ddays")


@router.delete("/ddays/{dday_id}", response_class=HTMLResponse)
async def delete_dday(request: Request, dday_id: int):
    S = request.app.state
    pid = S.get_profile_id(request)
    with S.get_db() as conn:
        conn.execute("DELETE FROM ddays WHERE id=? AND profile_id=?", (dday_id, pid))
    return HTMLResponse("")
