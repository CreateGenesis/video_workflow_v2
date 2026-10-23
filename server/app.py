"""cvgen v2 HTTP service. Routers live in server/api; execution happens in workers (python -m server.worker)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import insert, select, text

from . import db
from .api import admin, audit, auth_routes, devices, explore, library, tasks, v1, workflows
from .api.common import install_error_handlers
from .auth import SYSTEM, Principal, current_principal
from .catalog import catalog
from .config import ROOT, get_settings

log = logging.getLogger("cvgen.app")
SKILLS = ROOT / "skills"
AGENT_DOCS = ROOT / "docs" / "agent"
TOOL_FILES = {"linux": "cvgen-linux-x64.zip", "macos": "cvgen-macos.zip", "windows": "cvgen-windows-x64.zip"}


def bootstrap() -> None:
    """Idempotent first-start setup: a default workspace, system pools, providers from legacy env."""
    from .providers.instances import seed

    with db.tx() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(4243)"))
        if not conn.execute(select(db.workspaces.c.id).limit(1)).first():
            conn.execute(insert(db.workspaces).values(id=db.new_id("ws"), name="默认工作区", created_by="system"))
        created = seed(conn, SYSTEM)
    if created:
        log.info("seeded provider instances: %s", ", ".join(created))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings().tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        bootstrap()
    except Exception:
        log.exception("bootstrap failed; run `python -m server.manage migrate` first")
    yield


app = FastAPI(title="cvgen", version="2.0.0", lifespan=lifespan, docs_url="/v1/docs", openapi_url="/v1/openapi.json")
install_error_handlers(app)
for router in (auth_routes.router, admin.router, admin.workspaces_router, devices.router, explore.router, tasks.router,
               library.router, workflows.router, audit.router, v1.router):
    app.include_router(router)


@app.get("/api/health")
def health() -> dict:
    with db.tx() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


@app.get("/api/cli")
def cli_catalog(request: Request, principal: Principal = Depends(current_principal)) -> dict:
    data = catalog()
    data["client_version"] = request.headers.get("x-cvgen-client", "")
    return data


def _skill_files() -> dict[str, Path]:
    files = {path.stem: path for path in sorted(SKILLS.glob("*.md"))}
    files.update({f"agent-{path.stem}": path for path in sorted(AGENT_DOCS.glob("*.md"))})
    return files


@app.get("/api/skills")
def skills(principal: Principal = Depends(current_principal)) -> dict:
    items = []
    for name, path in _skill_files().items():
        first = next((line.strip("# ").strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()), name)
        items.append({"name": name, "title": first})
    return {"items": items}


@app.get("/api/skills/{name}", response_class=PlainTextResponse)
def skill(name: str, principal: Principal = Depends(current_principal)) -> str:
    path = _skill_files().get(name)
    if not path:
        raise HTTPException(status_code=404, detail="没有这份操作手册")
    return path.read_text(encoding="utf-8")


@app.get("/api/tools")
def tools(principal: Principal = Depends(current_principal)) -> dict:
    releases = get_settings().releases_dir
    version_file = releases / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else ""
    items = []
    for platform, filename in TOOL_FILES.items():
        path = releases / filename
        items.append({"platform": platform, "filename": filename, "ready": path.is_file(),
                      "bytes": path.stat().st_size if path.is_file() else 0, "version": version,
                      "url": f"/api/tools/{platform}"})
    return {"items": items, "version": version}


@app.get("/api/tools/{platform}")
def tool_download(platform: str, principal: Principal = Depends(current_principal)):
    filename = TOOL_FILES.get(platform)
    if not filename:
        raise HTTPException(status_code=404, detail="没有这个平台")
    path = get_settings().releases_dir / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="工具包还没有构建")
    return FileResponse(path, filename=filename, media_type="application/zip")


_web = get_settings().web_dir
if (_web / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_web / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith(("api/", "v1/", "media/")):
        raise HTTPException(status_code=404, detail="没有这个接口")
    candidate = (_web / path).resolve()
    if path and candidate.is_file() and _web.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = _web / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<!doctype html><meta charset=utf-8><title>cvgen</title><p>网页还没有构建：cd web && npm run build</p>")
