"""Single-port production serving: serve the built SPA from FastAPI.

The Vite build writes to ``frontend/dist``. When that directory exists we
mount it as static assets and redirect any unknown (non-/api) path to
``index.html`` so client-side navigation keeps working.

Dev mode (``vite dev`` on :5173) is unaffected: the API stays CORS-open and
the SPA talks to it directly.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def dist_dir() -> Path | None:
    """Locate the built frontend, preferring the repo checkout layout."""
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "frontend" / "dist",  # repo checkout
        here.parent / "dist",               # installed/single-dir layout
    ]
    for c in candidates:
        if (c / "index.html").is_file():
            return c
    return None


def mount_spa(app: FastAPI) -> bool:
    """Mount the built SPA (if present) on the API app; returns whether mounted."""
    dist = dist_dir()
    if dist is None:
        return False

    index = dist / "index.html"

    @app.get("/", include_in_schema=False)
    def spa_index() -> FileResponse:
        return FileResponse(index)

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    for name in ("favicon.svg", "icons.svg"):
        f = dist / name
        if f.is_file():
            app.get(f"/{name}", include_in_schema=False)(
                lambda f=f: FileResponse(f)
            )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        # Anything under /api is an unknown API route -> 404, not index.html.
        if full_path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="unknown API route")
        return FileResponse(index)

    return True


def _enabled() -> bool:
    return os.environ.get("LAWRISK_SERVE_SPA", "1").lower() not in {"0", "false", "no"}


def mount_spa_if_available(app: FastAPI) -> None:
    if _enabled():
        mount_spa(app)
