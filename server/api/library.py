"""Library assets, uploads, and media delivery."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import artifacts, assets, db, graph
from ..auth import Principal, current_principal, need, optional_principal
from ..config import get_settings
from ..security import verify_media
from ..storage import get_store
from .common import artifact_public

router = APIRouter(tags=["library"])
MAX_UPLOAD_BYTES = 4 * 1024 ** 3


class AssetIn(BaseModel):
    workspace_id: str
    name: str
    kind: str
    title: str = ""
    data: dict = Field(default_factory=dict)
    artifact_id: str | None = None
    note: str = ""


class PromoteIn(BaseModel):
    entity_id: str
    name: str
    note: str = ""


def _asset_view(conn, item: dict) -> dict:
    versions = assets.versions(conn, item["id"])
    return {**item, "versions": [{**version, "artifact": artifact_public(conn, version.get("artifact_id")),
                                  "ref": assets.format_ref(item["name"], version["version"])} for version in versions]}


@router.get("/api/assets")
def list_assets(workspace_id: str, kind: str = "", principal: Principal = Depends(need("assets:read"))) -> dict:
    principal.check_workspace(workspace_id)
    with db.tx() as conn:
        items = assets.list_assets(conn, workspace_id, kind or None)
        result = []
        for item in items:
            latest = assets.get_version(conn, workspace_id, item["name"], item["latest"])
            result.append({**item, "ref": assets.format_ref(item["name"], item["latest"]), "data": latest["data"],
                           "artifact": artifact_public(conn, latest.get("artifact_id"))})
        return {"items": result}


@router.get("/api/assets/{workspace_id}/{name}")
def get_asset(workspace_id: str, name: str, principal: Principal = Depends(need("assets:read"))) -> dict:
    principal.check_workspace(workspace_id)
    with db.tx() as conn:
        item = assets.get_asset(conn, workspace_id, name)
        if not item:
            raise HTTPException(status_code=404, detail="没有这个素材")
        return _asset_view(conn, item)


@router.post("/api/assets")
def save_asset(body: AssetIn, principal: Principal = Depends(need("assets:write"))) -> dict:
    with db.tx() as conn:
        if body.artifact_id:
            row = artifacts.get(conn, body.artifact_id)
            if not row or row["workspace_id"] != body.workspace_id:
                raise HTTPException(status_code=404, detail="没有这个文件")
        version = assets.create_or_version(conn, principal, body.workspace_id, body.name, body.kind, body.data,
                                           title=body.title, artifact_id=body.artifact_id, note=body.note)
        return {**version, "artifact": artifact_public(conn, version.get("artifact_id"))}


@router.post("/api/assets/promote")
def promote(body: PromoteIn, principal: Principal = Depends(need("assets:write"))) -> dict:
    """Lift an entity from a work into the library as a new asset version, so other works can reuse it."""
    with db.tx() as conn:
        entity = graph.require_entity(conn, body.entity_id)
        work = graph.require_work(conn, entity["work_id"])
        data = {key: value for key, value in entity["data"].items() if key != "prompt_versions"}
        version = assets.create_or_version(conn, principal, work["workspace_id"], body.name, entity["type"], data,
                                           title=data.get("title", ""), artifact_id=entity.get("artifact_id"),
                                           note=body.note or f"由 {work['title']} 的 {entity['id']} 提升")
        return {**version, "artifact": artifact_public(conn, version.get("artifact_id"))}


@router.post("/api/uploads")
def upload(
    file: UploadFile = File(...),
    workspace_id: str = Form(...),
    label: str = Form(""),
    principal: Principal = Depends(need("uploads:write")),
) -> dict:
    principal.check_workspace(workspace_id)
    suffix = Path(file.filename or "").suffix.lower()[:10]
    with tempfile.TemporaryDirectory(dir=get_settings().tmp_dir if get_settings().tmp_dir.exists() else None) as tmp:
        path = Path(tmp) / f"upload{suffix}"
        size = 0
        with path.open("wb") as handle:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过 4 GB")
                handle.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="文件是空的")
        with db.tx() as conn:
            if not conn.execute(select(db.workspaces.c.id).where(db.workspaces.c.id == workspace_id)).first():
                raise HTTPException(status_code=404, detail="没有这个工作区")
            row = artifacts.store_file(conn, workspace_id, path, prefix="uploads", mime=file.content_type or "",
                                       label=label or (file.filename or "上传文件"))
    return row


@router.get("/api/artifacts/{artifact_id}")
def artifact_info(artifact_id: str, principal: Principal = Depends(current_principal)) -> dict:
    with db.tx() as conn:
        row = artifacts.get(conn, artifact_id)
        if not row:
            raise HTTPException(status_code=404, detail="没有这个文件")
        principal.check_workspace(row["workspace_id"])
        return {**artifacts.public(row), "sha256": row["sha256"], "source_url": row["source_url"],
                "produced_by_task": row["produced_by_task"], "created_at": row["created_at"]}


@router.get("/media/{artifact_id}")
def media(artifact_id: str, request: Request, exp: int = 0, sig: str = "", download: int = 0):
    """Signed links work in <img>/<video> without headers; a session or token works too."""
    if not (exp and verify_media(artifact_id, exp, sig)):
        principal = optional_principal(request)
        if not principal:
            raise HTTPException(status_code=401, detail="链接已过期，请刷新页面")
    with db.tx() as conn:
        row = artifacts.get(conn, artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail="没有这个文件")
    store = get_store()
    filename = row["label"] or artifact_id
    if not filename.lower().endswith(Path(row["object_key"]).suffix.lower()):
        filename += Path(row["object_key"]).suffix
    disposition = "attachment" if download else "inline"
    local = store.local_path(row["object_key"])
    headers = {"Cache-Control": "private, max-age=3600"}
    if local:
        return FileResponse(local, media_type=row["mime"], filename=filename, content_disposition_type=disposition,
                            headers=headers)
    return StreamingResponse(store.stream(row["object_key"]), media_type=row["mime"],
                             headers={**headers, "Content-Disposition": f"{disposition}; filename*=UTF-8''{_quote(filename)}"})


def _quote(name: str) -> str:
    from urllib.parse import quote

    return quote(name)
