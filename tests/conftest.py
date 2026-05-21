"""
Shared fixtures for all planner tests.

Each app is imported once with an isolated temp DB.
"""

import sys
import importlib
import atexit
import tempfile
import shutil
from pathlib import Path

import httpx
import pytest_asyncio

_cleanup_dirs: list[Path] = []


@atexit.register
def _cleanup():
    for d in _cleanup_dirs:
        shutil.rmtree(d, ignore_errors=True)


def _import_app(path: str, alias: str):
    """Import main.py from *path* with DB redirected to a temp directory."""
    if path not in sys.path:
        sys.path.insert(0, path)

    importlib.invalidate_caches()
    mod = importlib.import_module("main")
    sys.modules[alias] = mod
    sys.modules.pop("main", None)
    if path in sys.path:
        sys.path.remove(path)

    tmp = Path(tempfile.mkdtemp(prefix=f"test_{alias}_"))
    _cleanup_dirs.append(tmp)
    mod.DB_PATH = tmp / "test.db"

    if hasattr(mod, "UPLOAD_DIR"):
        mod.UPLOAD_DIR = tmp / "uploads"
        mod.UPLOAD_DIR.mkdir(exist_ok=True)
    if hasattr(mod, "WORKLOG_IMG_DIR"):
        mod.WORKLOG_IMG_DIR = tmp / "worklog_images"
        mod.WORKLOG_IMG_DIR.mkdir(exist_ok=True)

    mod.init_db()
    return mod.app, mod


jm_app, jm_mod = _import_app("/workspace/app_planners/jm", "jm_main")
my_app, my_mod = _import_app("/workspace/app_planners/my", "my_main")
work_app, work_mod = _import_app("/workspace/app_planners/work", "work_main")


# ---------------------------------------------------------------------------
# Shared async client fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def jm():
    transport = httpx.ASGITransport(app=jm_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def my():
    transport = httpx.ASGITransport(app=my_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def work():
    transport = httpx.ASGITransport(app=work_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
