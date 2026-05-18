"""Common middleware classes shared across planner apps."""

import asyncio
import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

__all__ = [
    "EventBus",
    "CSRFMiddleware",
    "SyncBroadcastMiddleware",
]


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
