"""Common middleware classes shared across planner apps."""

import asyncio
import uuid

import starlette.formparsers as _fp
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .utils import fix_mojibake

__all__ = [
    "EventBus",
    "CSRFMiddleware",
    "SyncBroadcastMiddleware",
    "patch_formparser_utf8",
]

_formparser_patched = False


def patch_formparser_utf8():
    """Patch Starlette FormParser to fix latin-1 → UTF-8 mojibake."""
    global _formparser_patched
    if _formparser_patched:
        return
    _orig_parse = _fp.FormParser.parse

    async def _utf8_parse(self) -> _fp.FormData:
        fd = await _orig_parse(self)
        fixed = []
        for k, v in fd.multi_items():
            if isinstance(v, str):
                v = fix_mojibake(v)
            k = fix_mojibake(k)
            fixed.append((k, v))
        return _fp.FormData(fixed)

    _fp.FormParser.parse = _utf8_parse
    _formparser_patched = True


class EventBus:
    def __init__(self):
        self._subscribers: dict[str, asyncio.Queue] = {}

    def subscribe(self) -> tuple[str, asyncio.Queue]:
        sid = uuid.uuid4().hex
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers[sid] = q
        return sid, q

    def unsubscribe(self, sid: str):
        self._subscribers.pop(sid, None)

    def broadcast(self, page: str):
        for q in self._subscribers.values():
            q.put_nowait(page)


class CSRFMiddleware(BaseHTTPMiddleware):
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    async def dispatch(self, request, call_next):
        if request.method in self.SAFE_METHODS:
            return await call_next(request)
        if request.url.path in ("/health", "/sse") or request.url.path.startswith("/static"):
            return await call_next(request)
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        host = request.headers.get("host", "")
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc != host:
                return JSONResponse({"error": "CSRF"}, status_code=403)
        elif referer:
            from urllib.parse import urlparse
            if urlparse(referer).netloc != host:
                return JSONResponse({"error": "CSRF"}, status_code=403)
        return await call_next(request)


class SyncBroadcastMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, event_bus, skip_paths=(), skip_prefixes=()):
        super().__init__(app)
        self.event_bus = event_bus
        self.skip_paths = skip_paths
        self.skip_prefixes = skip_prefixes

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and response.status_code < 400:
            path = request.url.path
            if path not in self.skip_paths and not any(path.startswith(p) for p in self.skip_prefixes):
                page = path.strip("/").split("/")[0] or "dashboard"
                page_map = {"quick-todo": "dashboard", "subtasks": "todos"}
                page = page_map.get(page, page)
                self.event_bus.broadcast(page)
        return response
