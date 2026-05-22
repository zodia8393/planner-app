"""Google OAuth 2.0 login router for planner apps.

Each app injects the following via app.state:
    app.state.get_db              — () -> contextmanager[Connection]
    app.state.redirect            — (Request, url) -> Response
    app.state.auth_profile_table  — str: "profiles" or "work_profiles"
    app.state.auth_cookie_name    — str: cookie name for profile identity
    app.state.auth_cookie_max_age — int: cookie max age in seconds
    app.state.auth_on_login       — optional callable(request, response, profile_id)
                                     for app-specific post-login steps (e.g. session tokens)
"""

import os
import secrets
import logging
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse

logger = logging.getLogger("google_auth")

router = APIRouter(prefix="/auth/google", tags=["auth"])

# ── Google OAuth2 constants ──
GOOGLE_CLIENT_ID = os.environ.get("GCAL_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GCAL_CLIENT_SECRET", "")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def _build_redirect_uri(request: Request) -> str:
    """Build the OAuth2 callback URI from the incoming request."""
    host = request.headers.get("host", "localhost:8000")
    scheme = request.headers.get(
        "x-forwarded-proto",
        request.headers.get("x-forwarded-scheme", request.url.scheme),
    )
    if "fly.dev" in host:
        scheme = "https"
    return f"{scheme}://{host}/auth/google/callback"


@router.get("/login")
async def google_login(request: Request):
    """Redirect to Google OAuth2 consent screen."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(400, "GCAL_CLIENT_ID 환경변수가 설정되지 않았습니다")

    # CSRF: random state token saved in cookie
    state = secrets.token_urlsafe(32)

    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _build_redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "state": state,
        "prompt": "select_account",
    })
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}")
    response.set_cookie(
        "google_oauth_state", state,
        max_age=600,  # 10 minutes
        httponly=True,
        secure=request.url.scheme == "https" or "fly.dev" in request.headers.get("host", ""),
        samesite="lax",
    )
    return response


@router.get("/callback")
async def google_callback(
    request: Request,
    code: str = "",
    error: str = "",
    state: str = "",
):
    """Handle Google OAuth2 callback: exchange code, fetch profile, upsert user."""
    S = request.app.state

    if error:
        logger.error(f"[GOOGLE_AUTH] Google returned error: {error}")
        raise HTTPException(400, f"Google 인증 오류: {error}")
    if not code:
        logger.error("[GOOGLE_AUTH] No code received")
        raise HTTPException(400, "Google 인증 코드가 없습니다")

    # CSRF: verify state
    cookie_state = request.cookies.get("google_oauth_state", "")
    if not cookie_state or cookie_state != state:
        logger.error("[GOOGLE_AUTH] State mismatch (CSRF check failed)")
        raise HTTPException(400, "인증 상태가 일치하지 않습니다 (CSRF)")

    redirect_uri = _build_redirect_uri(request)
    logger.info(f"[GOOGLE_AUTH] token exchange: redirect_uri={redirect_uri}")

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        logger.error(f"[GOOGLE_AUTH] token exchange failed: {resp.status_code} {resp.text[:300]}")
        raise HTTPException(400, f"Google 토큰 교환 실패: {resp.text[:200]}")

    token_data = resp.json()
    access_token = token_data["access_token"]

    # Fetch user info
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        logger.error(f"[GOOGLE_AUTH] userinfo failed: {resp.status_code}")
        raise HTTPException(400, "Google 사용자 정보를 가져올 수 없습니다")

    userinfo = resp.json()
    google_sub = userinfo.get("sub", "")
    google_email = userinfo.get("email", "")
    google_name = userinfo.get("name", google_email.split("@")[0] if google_email else "사용자")

    if not google_sub:
        raise HTTPException(400, "Google 사용자 ID를 가져올 수 없습니다")

    logger.info(f"[GOOGLE_AUTH] user: sub={google_sub}, email={google_email}, name={google_name}")

    profile_table = S.auth_profile_table
    cookie_name = S.auth_cookie_name
    cookie_max_age = getattr(S, "auth_cookie_max_age", 365 * 24 * 3600)

    # Check if this is a "link" flow (linking Google to existing profile)
    is_link = state.startswith("link:")
    link_pid = None
    if is_link:
        parts = state.split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            link_pid = int(parts[1])

    with S.get_db() as conn:
        if is_link and link_pid:
            # Link mode: attach Google account to existing profile
            # Check if this google_sub is already linked to another profile
            existing = conn.execute(
                f"SELECT id FROM {profile_table} WHERE google_sub=? AND id!=?",
                (google_sub, link_pid),
            ).fetchone()
            if existing:
                logger.warning(f"[GOOGLE_AUTH] google_sub already linked to profile {existing['id']}")
                raise HTTPException(400, "이 Google 계정은 이미 다른 프로필에 연결되어 있습니다")

            conn.execute(
                f"UPDATE {profile_table} SET google_sub=?, google_email=? WHERE id=?",
                (google_sub, google_email, link_pid),
            )
            logger.info(f"[GOOGLE_AUTH] linked google to existing profile: id={link_pid}")

            response = RedirectResponse("/settings", status_code=303)
            response.delete_cookie("google_oauth_state")
            return response

        # Login mode: find or create profile
        row = conn.execute(
            f"SELECT * FROM {profile_table} WHERE google_sub=?",
            (google_sub,),
        ).fetchone()

        if row:
            # Existing Google-linked profile: update email if changed
            profile_id = row["id"]
            if dict(row).get("google_email") != google_email:
                conn.execute(
                    f"UPDATE {profile_table} SET google_email=? WHERE id=?",
                    (google_email, profile_id),
                )
            logger.info(f"[GOOGLE_AUTH] existing profile: id={profile_id}")
        else:
            # No profile linked to this Google account — create new
            profile_id = _create_profile(conn, S, profile_table, google_sub, google_email, google_name)
            logger.info(f"[GOOGLE_AUTH] new profile created: id={profile_id}")

        # Get the token for cookie (for My planner's token-based auth)
        token_val = _get_cookie_value(conn, profile_table, profile_id)

    # Build response
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        cookie_name, token_val,
        max_age=cookie_max_age,
        httponly=True,
        secure=request.url.scheme == "https" or "fly.dev" in request.headers.get("host", ""),
        samesite="lax",
    )
    # Clear the state cookie
    response.delete_cookie("google_oauth_state")

    # App-specific post-login hook (e.g. Work planner sets session token)
    on_login = getattr(S, "auth_on_login", None)
    if on_login:
        response = on_login(request, response, profile_id)

    return response


@router.get("/link")
async def google_link(request: Request):
    """Link Google account to existing profile (must be logged in)."""
    S = request.app.state
    pid = S.get_profile_id(request)
    if not pid:
        raise HTTPException(401, "로그인이 필요합니다")

    if not GOOGLE_CLIENT_ID:
        raise HTTPException(400, "GCAL_CLIENT_ID 환경변수가 설정되지 않았습니다")

    state = f"link:{pid}:{secrets.token_urlsafe(16)}"

    params = urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": _build_redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "state": state,
        "prompt": "select_account",
    })
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}")
    response.set_cookie(
        "google_oauth_state", state,
        max_age=600,
        httponly=True,
        secure=request.url.scheme == "https" or "fly.dev" in request.headers.get("host", ""),
        samesite="lax",
    )
    return response


# ── Internal helpers ──

def _create_profile(conn, S, profile_table: str, google_sub: str, google_email: str, google_name: str) -> int:
    """Create a new profile for a Google user. Handles different table schemas."""
    import uuid

    if profile_table == "profiles":
        # My planner: profiles(name, token, last_ip, google_sub, google_email)
        token = uuid.uuid4().hex + uuid.uuid4().hex
        cursor = conn.execute(
            "INSERT INTO profiles (name, token, google_sub, google_email) VALUES (?, ?, ?, ?)",
            (google_name, token, google_sub, google_email),
        )
        profile_id = cursor.lastrowid
        # Create default categories if the function exists
        ensure_cats = getattr(S, "ensure_default_categories", None)
        if ensure_cats:
            ensure_cats(conn, profile_id)
    else:
        # JM/Work planner: work_profiles(name, emoji, role, pin, google_sub, google_email)
        cursor = conn.execute(
            "INSERT INTO work_profiles (name, emoji, google_sub, google_email) VALUES (?, ?, ?, ?)",
            (google_name, "👤", google_sub, google_email),
        )
        profile_id = cursor.lastrowid

    return profile_id


def _get_cookie_value(conn, profile_table: str, profile_id: int) -> str:
    """Get the value to put in the profile cookie.

    My planner uses UUID token; JM/Work use profile ID string.
    """
    if profile_table == "profiles":
        row = conn.execute(
            "SELECT token FROM profiles WHERE id=?", (profile_id,)
        ).fetchone()
        return row["token"] if row else str(profile_id)
    return str(profile_id)
