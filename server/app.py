"""Read and operate the cloud video system. Execution stays here."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .catalog import commands as catalog_commands
from .compose import compose
from .providers import fetch_models, probe as probe_provider, public_view, save as save_provider, select_model
from .jobs import JobRunner
from .proxy import fetch as proxy_fetch
from .rules import passthrough_allowed, shot_status
from .scope import can_retry, ensure_scope, in_selected_work, require_selection, restore_prompt, stamp_work, tidy_positions, work_of_shot, work_scope, workspace_of_work
from .ontology import document, load_relations, load_types
from .admin_auth import bootstrap_password, hash_password, new_session, verify_password
from .storage import Storage, local_media_path
from .stories import seed_zero_carry
from .store import Store

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("CVGEN_DATA", ROOT / "data"))
PUBLIC = os.environ.get("CVGEN_PUBLIC_BASE", "http://127.0.0.1:8080")
WEB = ROOT / "web" / "dist"
RELEASES = ROOT / "tools" / "dist"
TOOL_FILES = {
    "linux": "cvgen-linux-x64.zip",
    "macos": "cvgen-macos.zip",
    "windows": "cvgen-windows-x64.zip",
}

store = Store(DATA / "cvgen.sqlite")
storage = Storage(DATA)
runner = JobRunner(store, storage, PUBLIC, DATA)
app = FastAPI(title="cvgen")


@app.on_event("startup")
def resume_open_jobs() -> None:
    ensure_scope(store)
    runner.resume_open()


if WEB.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


class EntityIn(BaseModel):
    type: str
    data: dict
    object_key: str | None = None


class LinkIn(BaseModel):
    name: str
    source_id: str
    target_id: str
    note: str = ""


class GenerateIn(BaseModel):
    shot_id: str
    resolution: str = "768p横"
    force: bool = False


class JobIn(BaseModel):
    target_id: str | None = None
    detail: dict = {}


ONLINE_SECONDS = 90


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        return ""
    return authorization.removeprefix("Bearer ").strip()


def require_admin(authorization: str | None) -> None:
    token = _bearer(authorization)
    saved = store.setting("admin_session")
    if not token or not saved or token != saved:
        raise HTTPException(status_code=401, detail="管理员未登录")


def require_reader(authorization: str | None) -> None:
    token = _bearer(authorization)
    saved = store.setting("admin_session")
    if token and saved and token == saved:
        return
    device = store.device_by_token(token) if token else None
    if device and device["status"] == "approved" and store.setting("active_device") == device["code"]:
        store.touch_device(device["code"])
        return
    raise HTTPException(status_code=401, detail="管理员未登录")


def require_agent(authorization: str | None) -> dict:
    token = _bearer(authorization)
    device = store.device_by_token(token) if token else None
    if not device or device["status"] != "approved":
        raise HTTPException(status_code=401, detail="cvgen 未授权")
    if store.setting("active_device") != device["code"]:
        raise HTTPException(status_code=401, detail="这台 cvgen 已离线")
    store.touch_device(device["code"])
    return device


def online_cvgen() -> dict | None:
    code = store.setting("active_device")
    if not code:
        return None
    device = store.device(code)
    if not device or device["status"] != "approved" or not device.get("seen_at"):
        return None
    seen = datetime.fromisoformat(device["seen_at"])
    if datetime.now(timezone.utc) - seen > timedelta(seconds=ONLINE_SECONDS):
        return None
    return {"code": device["code"], "seen_at": device["seen_at"], "status": "在线"}


def view(work_id: str | None = None) -> dict:
    ensure_scope(store)
    entities = store.list_entities()
    links = store.all_links()
    jobs = store.list_jobs()
    allowed = work_scope(store, work_id) if work_id else None
    if allowed is not None:
        entities = [entity for entity in entities if entity["id"] in allowed]
        links = [link for link in links if link["source_id"] in allowed and link["target_id"] in allowed]
        jobs = [job for job in jobs if job.get("target_id") in allowed]
    nodes = []
    for entity in entities:
        title = entity["data"].get("title") or entity["id"]
        nodes.append({
            "id": entity["id"],
            "type": entity["type"],
            "title": title,
            "summary": _summary(entity),
            "object_key": entity["object_key"],
            "preview_url": _site_url(entity["object_key"]),
            "status": _status(entity["id"], jobs),
            "position": _position(work_id, entity["id"]) if work_id else {},
        })
    edges = []
    relation_text = load_relations()
    for link in links:
        label = relation_text.get(link["name"], {}).get("label", link["name"])
        edges.append({**link, "label": label, "plain": link.get("note") or label})
    return {
        "nodes": nodes,
        "edges": edges,
        "jobs": [_public_job(job) for job in jobs],
        "workspaces": _workspaces(),
        "works": [item for item in _works(store.setting("selected_workspace")) if item["id"] == (work_id or store.setting("selected_work"))],
        "selected": {
            "workspace_id": store.setting("selected_workspace"),
            "work_id": store.setting("selected_work"),
        },
        "settings": {
            "ffmpeg_passthrough": store.setting("ffmpeg_passthrough", "0") == "1",
            "public_base": PUBLIC,
            "admin_ready": bool(store.setting("admin_password")),
            "cvgen": online_cvgen(),
            "providers": public_view(store),
        },
    }


def _site_url(object_key: str | None) -> str:
    if not object_key:
        return ""
    if object_key.startswith(("http://", "https://")):
        try:
            return remember_remote(object_key)
        except Exception:
            return ""
    return storage.signed_url(object_key, PUBLIC)


def _summary(entity: dict) -> str:
    data = entity["data"]
    if entity["type"] == "Shot":
        return f"{data.get('size', '')}，{data.get('action', '')}"
    return data.get("summary") or data.get("text") or data.get("facts") or data.get("medium") or ""


def _status(entity_id: str, jobs: list[dict]) -> str:
    related = [job for job in jobs if job["target_id"] == entity_id]
    return shot_status(related)


def _position(work_id: str | None, entity_id: str) -> dict:
    if not work_id:
        return {}
    import json
    raw = store.setting(f"layout:{work_id}", "{}")
    try:
        saved = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    item = saved.get(entity_id) or {}
    if "x" not in item or "y" not in item:
        return {}
    return {"x": item["x"], "y": item["y"]}


def _workspaces() -> list[dict]:
    return [{"id": item["id"], "title": item["data"].get("title") or item["id"]} for item in store.list_entities("Workspace")]


def _works(workspace_id: str) -> list[dict]:
    if not workspace_id:
        return []
    owned = {
        link["target_id"] for link in store.all_links()
        if link["name"] == "contains" and link["source_id"] == workspace_id
    }
    return [
        {"id": item["id"], "title": item["data"].get("title") or item["id"], "kind": item["data"].get("kind") or ""}
        for item in store.list_entities("Work") if item["id"] in owned
    ]


def _selected_work() -> str:
    ensure_scope(store)
    _workspace, work_id = require_selection(store)
    return work_id


def _bind_shot(entity: dict) -> None:
    if entity["type"] != "Shot":
        return
    work_id = _selected_work()
    store.add_link("belongs_to", entity["id"], work_id, "当前作品")


def _guard_link(name: str, source_id: str, target_id: str) -> None:
    if name in {"contains", "belongs_to"}:
        return
    work_id = _selected_work()
    for entity_id in (source_id, target_id):
        if not in_selected_work(store, entity_id, work_id):
            raise ValueError("不能连入另一个作品的实体")


def _require_shot_in_work(shot_id: str) -> str:
    work_id = _selected_work()
    if not in_selected_work(store, shot_id, work_id):
        raise ValueError("不能操作另一个作品")
    return work_id


def _job_targets(target_id: str | None, detail: dict | None) -> list[str]:
    found: list[str] = []
    if target_id:
        found.append(target_id)
    for value in (detail or {}).values():
        candidates = value if isinstance(value, list) else [value]
        for item in candidates:
            if not isinstance(item, str) or not item:
                continue
            try:
                store.get_entity(item)
            except KeyError:
                continue
            found.append(item)
    return found


def _require_job_in_work(target_id: str | None, detail: dict | None = None) -> str:
    """A selected work cannot start a job against another work's entities."""
    work_id = _selected_work()
    for entity_id in _job_targets(target_id, detail):
        try:
            store.get_entity(entity_id)
        except KeyError:
            continue
        if not in_selected_work(store, entity_id, work_id):
            raise ValueError("不能操作另一个作品")
    return work_id


def _public_job(job: dict) -> dict:
    detail = dict(job["detail"])
    for key in ("sheet_key", "last_key", "object_key"):
        if detail.get(key):
            detail[key + "_url"] = _site_url(detail[key])
    return {**job, "detail": detail}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/auth/status")
def auth_status() -> dict:
    return {"admin_ready": bool(store.setting("admin_password"))}


@app.get("/api/tools")
def tools(authorization: str | None = Header(default=None)) -> dict:
    require_reader(authorization)
    items = []
    for platform, filename in TOOL_FILES.items():
        path = RELEASES / filename
        items.append({
            "platform": platform,
            "filename": filename,
            "ready": path.is_file(),
            "bytes": path.stat().st_size if path.is_file() else 0,
            "url": f"/api/tools/{platform}",
        })
    return {"items": items}


@app.get("/api/tools/{platform}")
def tool_download(platform: str, authorization: str | None = Header(default=None)):
    require_reader(authorization)
    filename = TOOL_FILES.get(platform)
    if not filename:
        raise HTTPException(status_code=404, detail="没有这个平台")
    path = RELEASES / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="工具包还没有构建")
    return FileResponse(
        path,
        filename=filename,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/device/start")
def device_start() -> dict:
    code = secrets.token_hex(3)
    store.save_device(code, "pending")
    return {"code": code, "approve_url": f"{PUBLIC}/approve/{code}"}


@app.post("/api/device/{code}/approve")
def device_approve(code: str, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    if not store.device(code):
        raise HTTPException(status_code=404, detail="没有这个设备码")
    current = online_cvgen()
    if current and current["code"] != code:
        raise HTTPException(status_code=409, detail="已有一台 cvgen 在线，先下线再批准")
    token = secrets.token_urlsafe(24)
    store.save_device(code, "approved", token, datetime.now(timezone.utc).isoformat())
    store.set_setting("active_device", code)
    return {"approved": True}


@app.get("/api/device/{code}")
def device_poll(code: str) -> dict:
    item = store.device(code)
    if not item:
        raise HTTPException(status_code=404, detail="没有这个设备码")
    if item["status"] != "approved":
        return {"status": "pending"}
    return {"status": "approved", "token": item["token"], "base": PUBLIC}


@app.get("/api/ontology")
def ontology(authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    return document()


@app.get("/api/view")
def api_view(work_id: str = "", authorization: str | None = Header(default=None)) -> dict:
    require_reader(authorization)
    chosen = work_id or store.setting("selected_work")
    return view(chosen or None)


@app.get("/api/cli")
def cli_catalog(authorization: str | None = Header(default=None)) -> dict:
    require_reader(authorization)
    return {"commands": catalog_commands()}


@app.get("/api/canvas")
def canvas(authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    data = view(store.setting("selected_work") or None)
    return {
        "nodes": data["nodes"],
        "edges": data["edges"],
        "jobs": data["jobs"],
    }


@app.post("/api/entity")
def add_entity(body: EntityIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    types = load_types()
    if body.type not in types:
        raise HTTPException(status_code=400, detail="类型不在原型里")
    missing = [field["name"] for field in types[body.type]["fields"] if field["required"] and not body.data.get(field["name"])]
    if missing:
        raise HTTPException(status_code=400, detail="缺少必填：" + ",".join(missing))
    try:
        work_id = _selected_work()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = stamp_work(body.data, work_id)
    entity = store.add_entity(body.type, data, body.object_key)
    _bind_shot(entity)
    store.record("entity add", {"id": entity["id"], "type": body.type})
    return entity


@app.get("/api/entity/{entity_id}")
def get_entity(entity_id: str, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        return store.get_entity(entity_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="没有这个实体") from exc


@app.get("/api/entities")
def list_entities(type: str | None = None, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    return {"items": store.list_entities(type)}


@app.post("/api/link")
def add_link(body: LinkIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    relations = load_relations()
    if body.name not in relations:
        raise HTTPException(status_code=400, detail="关系不在原型里")
    try:
        source = store.get_entity(body.source_id)
        target = store.get_entity(body.target_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="实体不存在") from exc
    rule = relations[body.name]
    source_ok = source["type"] == rule["from"] or (body.name == "references" and source["type"] == "Voice")
    if not source_ok or target["type"] != rule["to"]:
        raise HTTPException(status_code=400, detail=f"这条关系只能从 {rule['from']} 连到 {rule['to']}")
    if body.name == "shot_with" and store.links(body.source_id, "shot_with"):
        raise HTTPException(status_code=400, detail="一条镜头只能有一种运镜")
    try:
        _guard_link(body.name, body.source_id, body.target_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    link = store.add_link(body.name, body.source_id, body.target_id, body.note)
    store.record("link", link)
    return link


@app.post("/api/derive")
def derive(body: LinkIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        source = store.get_entity(body.source_id)
        target = store.get_entity(body.target_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="实体不存在") from exc
    if source["type"] not in {"Clip", "Reference"} or target["type"] not in {"Clip", "Reference"}:
        raise HTTPException(status_code=400, detail="derived_from 只能指向已经存在的成片或参考")
    try:
        _guard_link("derived_from", body.source_id, body.target_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    link = store.add_link("derived_from", body.source_id, body.target_id, body.note)
    store.record("derive", link)
    return link


@app.get("/api/shot/{shot_id}/compose")
def shot_compose(shot_id: str, resolution: str = "768p横", authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_shot_in_work(shot_id)
        plan = compose(store, shot_id, resolution)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.record("shot compose", {"shot_id": shot_id, "warnings": plan["warnings"]})
    return plan


@app.post("/api/stories/zero")
def story_zero(authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    seeded = seed_zero_carry(store)
    store.record("story zero", seeded)
    return seeded


@app.post("/api/generate")
def generate(body: GenerateIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_shot_in_work(body.shot_id)
        job = runner.start("generate", body.shot_id, {"resolution": body.resolution, "force": body.force, "work_id": store.setting("selected_work")})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store.record("generate", job)
    return job


@app.post("/api/tts")
def tts(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_job_in_work(body.target_id, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = runner.start("tts", body.target_id, {**body.detail, "work_id": store.setting("selected_work")})
    store.record("tts", job)
    return job


@app.post("/api/pull")
def pull(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_job_in_work(None, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = runner.start("pull", None, {**body.detail, "work_id": store.setting("selected_work")})
    store.record("pull", job)
    return job


@app.post("/api/inspect")
def inspect(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_job_in_work(body.target_id, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runner.start("inspect", body.target_id, {**body.detail, "work_id": store.setting("selected_work")})


@app.post("/api/reverse")
def reverse(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_job_in_work(body.target_id, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runner.start("reverse", body.target_id, {**body.detail, "work_id": store.setting("selected_work")})


@app.post("/api/learn")
def learn(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_job_in_work(None, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runner.start("learn", None, {**body.detail, "work_id": store.setting("selected_work")})


@app.post("/api/style")
def style(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_job_in_work(body.target_id, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runner.start("style", body.target_id, {**body.detail, "work_id": store.setting("selected_work")})


@app.post("/api/edit")
def edit(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    detail = dict(body.detail)
    try:
        _require_job_in_work(body.target_id, detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    detail["work_id"] = store.setting("selected_work")
    if detail.get("op") in {"export", "mix", "subtitle"} and body.target_id:
        try:
            edit_entity = store.get_entity(body.target_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="没有这个剪辑") from exc
        if edit_entity["type"] != "Edit":
            raise HTTPException(status_code=400, detail="只能导出剪辑")
        detail["clips"] = detail.get("clips") or [link["target_id"] for link in store.links(body.target_id, "uses_clip")]
        detail["narration"] = detail.get("narration") or (edit_entity["data"].get("narration") or "")
        detail["music"] = detail.get("music") or (edit_entity["data"].get("music") or "")
        detail["lines"] = detail.get("lines") or (edit_entity["data"].get("lines") or [])
        detail["title"] = edit_entity["data"].get("title") or "剪辑成片"
    return runner.start("edit", body.target_id, detail)


@app.post("/api/media")
def upload_media(
    file: UploadFile = File(...),
    kind: str = Form(...),
    title: str = Form(""),
    role: str = Form("细节"),
    authorization: str | None = Header(default=None),
) -> dict:
    require_agent(authorization)
    from .ontology import ROLES

    if kind not in {"image", "video", "audio"}:
        raise HTTPException(status_code=400, detail="文件种类只能是 image、video 或 audio")
    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="文件是空的")
    suffix = Path(file.filename or "media.bin").suffix.lower() or ".bin"
    if len(suffix) > 8 or not suffix.startswith(".") or "/" in suffix or "\\" in suffix:
        suffix = ".bin"
    name = Path(file.filename or "素材").stem
    try:
        work_id = _selected_work()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if kind == "image":
        if role not in ROLES:
            raise HTTPException(status_code=400, detail="参考用途不在原型里")
        key = storage.put("references", f"{secrets.token_hex(8)}{suffix}", payload, file.content_type or "application/octet-stream")
        entity = store.add_entity("Reference", stamp_work({"title": title or name, "role": role, "take": "", "ignore": ""}, work_id), key)
    else:
        key = storage.put("clips", f"{secrets.token_hex(8)}{suffix}", payload, file.content_type or "application/octet-stream")
        entity = store.add_entity("Clip", stamp_work({"title": title or name, "duration": 0}, work_id), key)
    store.record("media upload", {"id": entity["id"], "kind": kind})
    return entity


@app.post("/api/frame")
def extract_frame(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    at = (body.detail or {}).get("at") or "last"
    role = (body.detail or {}).get("role") or "空间"
    if at not in {"first", "last"}:
        raise HTTPException(status_code=400, detail="抽帧位置只能是 first 或 last")
    if role not in {"首帧", "尾帧", "空间"}:
        raise HTTPException(status_code=400, detail="抽帧用途只能是首帧、尾帧或空间")
    try:
        _require_job_in_work(body.target_id, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runner.start("frame", body.target_id, {"at": at, "role": role, "work_id": store.setting("selected_work")})


@app.post("/api/image")
def image_job(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    from .providers import configured

    try:
        _require_job_in_work(body.target_id, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not configured(store, "image"):
        raise HTTPException(status_code=400, detail="生图还没有配置，不能提交")
    return runner.start("image", body.target_id, {**body.detail, "work_id": store.setting("selected_work")})


@app.post("/api/music")
def music_job(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    from .providers import configured

    try:
        _require_job_in_work(body.target_id, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not configured(store, "music"):
        raise HTTPException(status_code=400, detail="生音乐还没有配置，不能提交")
    return runner.start("music", body.target_id, {**body.detail, "work_id": store.setting("selected_work")})


@app.post("/api/check")
def check_clip(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        _require_job_in_work(body.target_id, body.detail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return runner.start("check", body.target_id, {**body.detail, "work_id": store.setting("selected_work")})


@app.post("/api/reference")
def upload_reference(
    file: UploadFile = File(...),
    role: str = Form(...),
    title: str = Form(""),
    take: str = Form(""),
    ignore: str = Form(""),
    authorization: str | None = Header(default=None),
) -> dict:
    require_agent(authorization)
    from .ontology import ROLES

    if role not in ROLES:
        raise HTTPException(status_code=400, detail="参考用途不在原型里")
    try:
        work_id = _selected_work()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="参考文件是空的")
    suffix = Path(file.filename or "ref.bin").suffix.lower() or ".bin"
    if len(suffix) > 8 or not suffix.startswith(".") or "/" in suffix or "\\" in suffix:
        suffix = ".bin"
    key = storage.put("references", f"{secrets.token_hex(8)}{suffix}", payload, file.content_type or "application/octet-stream")
    entity = store.add_entity("Reference", stamp_work({
        "title": title or Path(file.filename or "参考").stem,
        "role": role,
        "take": take,
        "ignore": ignore,
    }, work_id), key)
    store.record("reference upload", {"id": entity["id"]})
    return entity


@app.post("/api/ffmpeg")
def ffmpeg_pass(body: JobIn, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    if not passthrough_allowed(store.setting("ffmpeg_passthrough", "0")):
        raise HTTPException(status_code=403, detail="ffmpeg 透传没有打开")
    return runner.start("ffmpeg", None, body.detail)


@app.get("/api/job/{job_id}")
def job_show(job_id: str, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    try:
        return _public_job(store.get_job(job_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="没有这个任务") from exc


@app.get("/api/preview/{entity_id}")
def preview(entity_id: str, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    entity = store.get_entity(entity_id)
    sheet = ""
    matched = None
    for job in store.list_jobs():
        detail = job.get("detail") or {}
        owns = job["target_id"] == entity_id or detail.get("clip_id") == entity_id
        if not owns:
            continue
        if matched is None:
            matched = job
        if detail.get("sheet_key") and not sheet:
            sheet = storage.signed_url(detail["sheet_key"], PUBLIC)
            matched = job
    status = "未生成"
    if matched:
        if matched["kind"] == "generate" and matched["target_id"]:
            status = _status(matched["target_id"], store.list_jobs())
        elif matched["status"] == "succeeded":
            status = "已成片"
        elif matched["status"] in {"queued", "running"}:
            status = "排队"
        elif matched["status"] == "unknown":
            status = "提交不明"
        elif matched["status"] == "failed":
            status = "失败"
    return {
        "id": entity_id,
        "title": entity["data"].get("title"),
        "preview_url": storage.signed_url(entity.get("object_key"), PUBLIC),
        "sheet_url": sheet,
        "status": status,
    }


@app.get("/api/skills")
def skills(authorization: str | None = Header(default=None)) -> dict:
    require_reader(authorization)
    folder = ROOT / "skills"
    names = sorted(path.stem for path in folder.glob("*.md"))
    return {"items": names}


@app.get("/api/skills/{name}")
def skill_show(name: str, authorization: str | None = Header(default=None)) -> dict:
    require_reader(authorization)
    path = ROOT / "skills" / f"{name}.md"
    if not path.is_file() or "/" in name or ".." in name:
        raise HTTPException(status_code=404, detail="没有这个技能")
    return {"name": name, "text": path.read_text(encoding="utf-8")}


@app.get("/api/batch/{work_id}")
def batch(work_id: str, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    shots = []
    for link in store.all_links():
        if link["name"] == "belongs_to" and link["target_id"] == work_id:
            shot = store.get_entity(link["source_id"])
            cameras = store.links(shot["id"], "shot_with")
            styles = store.links(shot["id"], "styled_as")
            shots.append({
                "id": shot["id"],
                "title": shot["data"].get("title"),
                "camera": cameras[0]["target_id"] if cameras else "",
                "style": styles[0]["target_id"] if styles else "",
                "status": _status(shot["id"], store.list_jobs()),
            })
    return {"work_id": work_id, "shots": shots}


class PlatformIn(BaseModel):
    name: str
    note: str = ""


class ProviderIn(BaseModel):
    capability: str
    base: str
    key: str = ""


class AdminIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    password: str
    next_password: str


class ProviderActionIn(BaseModel):
    capability: str
    keyword: str = ""
    source: str = ""


class ResetIn(BaseModel):
    recovery: str
    next_password: str


def _check_admin(username: str, password: str) -> None:
    saved_name = store.setting("admin_username")
    saved_hash = store.setting("admin_password")
    if not saved_hash or username != saved_name or not verify_password(password, saved_hash):
        raise HTTPException(status_code=401, detail="账号或密码不对")


@app.post("/api/admin/setup")
def admin_setup(body: AdminIn) -> dict:
    if store.setting("admin_password"):
        raise HTTPException(status_code=409, detail="管理员已经设置")
    if not body.username.strip():
        raise HTTPException(status_code=400, detail="账号不能为空")
    try:
        stored = hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.set_setting("admin_username", body.username.strip())
    store.set_setting("admin_password", stored)
    session = new_session()
    store.set_setting("admin_session", session)
    return {"token": session, "username": body.username.strip()}


@app.post("/api/admin/login")
def admin_login(body: AdminIn) -> dict:
    if not store.setting("admin_password"):
        seeded = bootstrap_password()
        if not seeded or body.password != seeded or not body.username.strip():
            raise HTTPException(status_code=401, detail="管理员还没有设置")
        store.set_setting("admin_username", body.username.strip())
        store.set_setting("admin_password", hash_password(body.password))
    _check_admin(body.username.strip(), body.password)
    session = new_session()
    store.set_setting("admin_session", session)
    return {"token": session, "username": body.username.strip()}


@app.get("/api/admin/session")
def admin_session(authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    return {"username": store.setting("admin_username"), "ok": True}


def _replace_password(next_password: str) -> str:
    try:
        store.set_setting("admin_password", hash_password(next_password))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session = new_session()
    store.set_setting("admin_session", session)
    return session


@app.post("/api/admin/password")
def admin_password(body: PasswordIn, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    if not verify_password(body.password, store.setting("admin_password")):
        raise HTTPException(status_code=401, detail="当前密码不对")
    session = _replace_password(body.next_password)
    return {"token": session, "username": store.setting("admin_username")}


@app.post("/api/admin/reset")
def admin_reset(body: ResetIn) -> dict:
    if not store.setting("admin_password"):
        raise HTTPException(status_code=400, detail="管理员还没有设置")
    expected = bootstrap_password()
    if not expected:
        raise HTTPException(status_code=403, detail="没有配置恢复口令")
    import hmac
    if not body.recovery or not hmac.compare_digest(body.recovery, expected):
        raise HTTPException(status_code=401, detail="恢复口令不对")
    session = _replace_password(body.next_password)
    return {"token": session, "username": store.setting("admin_username")}


@app.post("/api/admin/logout")
def admin_logout(authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    store.set_setting("admin_session", "")
    return {"ok": True}


@app.get("/api/admin/cvgen")
def admin_cvgen(authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    active = store.setting("active_device")
    current = online_cvgen()
    items = []
    for device in store.list_devices():
        items.append({
            "code": device["code"],
            "status": device["status"],
            "seen_at": device.get("seen_at"),
            "online": bool(current and current["code"] == device["code"]),
            "active": device["code"] == active,
        })
    return {"items": items, "online": current}


@app.post("/api/admin/cvgen/{code}/revoke")
def admin_revoke(code: str, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    if not store.device(code):
        raise HTTPException(status_code=404, detail="没有这台 cvgen")
    store.revoke_device(code)
    if store.setting("active_device") == code:
        store.set_setting("active_device", "")
    return {"revoked": True, "code": code}


@app.post("/api/settings/platform")
def platform_bind(body: PlatformIn, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="平台名称不能为空")
    store.set_setting(f"platform:{body.name.strip()}", body.note)
    return {"saved": True, "name": body.name.strip()}


@app.get("/api/settings/platform")
def platform_list(authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    return {"items": [
        {"name": key.split(":", 1)[1], "note": value}
        for key, value in _settings_like("platform:")
    ]}


def _settings_like(prefix: str) -> list[tuple[str, str]]:
    rows = store.conn.execute("SELECT key, value FROM settings WHERE key LIKE ?", (prefix + "%",)).fetchall()
    return [(row["key"], row["value"]) for row in rows]


@app.get("/api/settings/providers")
def provider_list(authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    return {"items": public_view(store)}


@app.post("/api/settings/providers")
def provider_save(body: ProviderIn, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    try:
        save_provider(store, body.capability, body.base, body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = next(item for item in public_view(store) if item["capability"] == body.capability)
    store.record("provider save", {"capability": body.capability, "configured": saved["configured"]})
    return saved


@app.post("/api/provider/probe")
def provider_probe(body: ProviderActionIn, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    try:
        result = probe_provider(store, body.capability)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.record("provider probe", {"capability": body.capability, "reachable": result["reachable"]})
    return result


@app.post("/api/provider/models")
def provider_models(body: ProviderActionIn, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    try:
        return fetch_models(store, body.capability)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/provider/model")
def provider_model(body: ProviderActionIn, authorization: str | None = Header(default=None)) -> dict:
    require_admin(authorization)
    try:
        select_model(store, body.capability, body.source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = next(item for item in public_view(store) if item["capability"] == body.capability)
    return saved


@app.post("/api/settings/passthrough")
def passthrough(enabled: bool, authorization: str | None = Header(default=None)) -> dict:
    require_agent(authorization)
    store.set_setting("ffmpeg_passthrough", "1" if enabled else "0")
    return {"ffmpeg_passthrough": enabled}


class TitleIn(BaseModel):
    title: str = ""
    kind: str = ""
    brief: str = ""
    id: str = ""


class PromptIn(BaseModel):
    text: str = ""
    index: int = 0


class LayoutIn(BaseModel):
    positions: dict = {}


def _reader_or_agent(authorization: str | None) -> None:
    try:
        require_reader(authorization)
    except HTTPException:
        require_agent(authorization)


@app.get("/api/workspaces")
def list_workspaces(authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    ensure_scope(store)
    return {"items": _workspaces(), "selected": store.setting("selected_workspace")}


@app.post("/api/workspaces")
def add_workspace(body: TitleIn, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="名称不能为空")
    return store.add_entity("Workspace", {"title": body.title.strip()})


@app.post("/api/workspaces/{workspace_id}/rename")
def rename_workspace(workspace_id: str, body: TitleIn, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    try:
        current = store.get_entity(workspace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="没有这个工作区") from exc
    if current["type"] != "Workspace":
        raise HTTPException(status_code=400, detail="没有这个工作区")
    data = dict(current["data"])
    data["title"] = body.title.strip() or data.get("title")
    return store.update_entity(workspace_id, data)


@app.post("/api/workspaces/use")
def use_workspace(body: TitleIn, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    try:
        current = store.get_entity(body.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="没有这个工作区") from exc
    if current["type"] != "Workspace":
        raise HTTPException(status_code=400, detail="没有这个工作区")
    store.set_setting("selected_workspace", body.id)
    if store.setting("selected_work"):
        try:
            if workspace_of_work(store, store.setting("selected_work")) != body.id:
                store.set_setting("selected_work", "")
        except ValueError:
            store.set_setting("selected_work", "")
    return {"workspace_id": body.id, "work_id": store.setting("selected_work")}


@app.get("/api/works")
def list_works(authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    ensure_scope(store)
    workspace_id = store.setting("selected_workspace")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="先选择工作区")
    return {"items": _works(workspace_id), "selected": store.setting("selected_work")}


@app.post("/api/works")
def add_work(body: TitleIn, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    ensure_scope(store)
    workspace_id = store.setting("selected_workspace")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="先选择工作区")
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="名称不能为空")
    work = store.add_entity("Work", {"title": body.title.strip(), "kind": body.kind, "brief": body.brief})
    store.add_link("contains", workspace_id, work["id"], "当前工作区")
    return work


@app.post("/api/works/use")
def use_work(body: TitleIn, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    workspace_id = store.setting("selected_workspace")
    if not workspace_id:
        raise HTTPException(status_code=400, detail="先选择工作区")
    try:
        if workspace_of_work(store, body.id) != workspace_id:
            raise ValueError("作品不在当前工作区")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.set_setting("selected_work", body.id)
    return {"workspace_id": workspace_id, "work_id": body.id}


@app.get("/api/work/current")
def current_work(authorization: str | None = Header(default=None)) -> dict:
    require_reader(authorization)
    try:
        work_id = _selected_work()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return view(work_id)


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    try:
        job = store.get_job(job_id)
        _selected_work()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="没有这个任务") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job["kind"] == "generate" and job["status"] == "unknown" and not (job.get("detail") or {}).get("provider_task"):
        store.update_job(job_id, "failed", job["detail"])
    allowed, reason = can_retry(job)
    if not allowed:
        raise HTTPException(status_code=409, detail=reason)
    if job.get("target_id") and not in_selected_work(store, job["target_id"], store.setting("selected_work")):
        raise HTTPException(status_code=400, detail="不能操作另一个作品")
    detail = {key: value for key, value in dict(job["detail"]).items() if key not in {"error", "submitted", "provider_task"}}
    detail["retried_from"] = job_id
    try:
        started = runner.start(job["kind"], job.get("target_id"), detail)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return started


@app.get("/api/shots/{shot_id}/prompt")
def prompt_show(shot_id: str, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    try:
        _require_shot_in_work(shot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"versions": _prompt_versions(shot_id)}


@app.post("/api/shots/{shot_id}/prompt")
def prompt_save(shot_id: str, body: PromptIn, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    try:
        _require_shot_in_work(shot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    versions = _prompt_versions(shot_id)
    shot = store.get_entity(shot_id)
    if not versions and shot["data"].get("action"):
        versions.append({"text": shot["data"]["action"], "at": shot.get("created_at") or datetime.now(timezone.utc).isoformat()})
    versions.append({"text": body.text, "at": datetime.now(timezone.utc).isoformat()})
    _write_prompt(shot_id, versions)
    return {"versions": versions}


@app.post("/api/shots/{shot_id}/prompt/restore")
def prompt_restore(shot_id: str, body: PromptIn, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    try:
        _require_shot_in_work(shot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    versions = _prompt_versions(shot_id)
    try:
        index = int(body.index)
        restored = restore_prompt(versions, index, versions[index]["text"] if 0 <= index < len(versions) else "")
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=400, detail="没有这一版") from exc
    stamped = [{**item, "at": item.get("at") or datetime.now(timezone.utc).isoformat()} for item in restored]
    if len(stamped) > len(versions):
        stamped[-1]["at"] = datetime.now(timezone.utc).isoformat()
    _write_prompt(shot_id, stamped)
    return {"versions": stamped}


def _prompt_versions(shot_id: str) -> list[dict]:
    import json
    try:
        shot = store.get_entity(shot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="没有这个镜头") from exc
    raw = shot["data"].get("prompt_versions") or "[]"
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = []
    return parsed if isinstance(parsed, list) else []


def _write_prompt(shot_id: str, versions: list[dict]) -> None:
    shot = store.get_entity(shot_id)
    data = dict(shot["data"])
    data["prompt_versions"] = versions
    if versions:
        data["action"] = versions[-1]["text"]
    store.update_entity(shot_id, data)


@app.post("/api/images/{entity_id}/redraw")
def redraw_image(entity_id: str, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    try:
        entity = store.get_entity(entity_id)
        work_id = _selected_work()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="没有这个图片") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if entity["type"] != "Reference" or not str(entity.get("object_key") or "").lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise HTTPException(status_code=400, detail="只能对已生成图片重新抽卡")
    if not in_selected_work(store, entity_id, work_id):
        raise HTTPException(status_code=400, detail="不能操作另一个作品")
    shot_id = next((link["source_id"] for link in store.all_links() if link["name"] == "references" and link["target_id"] == entity_id), "")
    if not shot_id:
        raise HTTPException(status_code=400, detail="图片没有连到镜头")
    previous = entity["object_key"]
    started = runner.start("image", shot_id, {"role": entity["data"].get("role") or "细节", "redraw_of": entity_id, "kept": previous})
    return {**started, "kept": previous}


@app.post("/api/layout")
def save_layout(body: LayoutIn, authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    import json
    try:
        work_id = _selected_work()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    before = len(store.all_links())
    allowed = work_scope(store, work_id)
    cleaned = {}
    for entity_id, point in (body.positions or {}).items():
        if entity_id not in allowed or not isinstance(point, dict):
            continue
        cleaned[entity_id] = {"x": int(point.get("x") or 0), "y": int(point.get("y") or 0)}
    store.set_setting(f"layout:{work_id}", json.dumps(cleaned))
    if len(store.all_links()) != before:
        raise HTTPException(status_code=500, detail="布局改变了关系")
    return {"positions": cleaned}


@app.post("/api/layout/tidy")
def tidy_layout(authorization: str | None = Header(default=None)) -> dict:
    _reader_or_agent(authorization)
    import json
    try:
        work_id = _selected_work()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    before = [link["id"] for link in store.all_links()]
    nodes = [{"id": entity["id"], "type": entity["type"]} for entity in store.list_entities() if entity["id"] in work_scope(store, work_id)]
    positions = tidy_positions(nodes)
    store.set_setting(f"layout:{work_id}", json.dumps(positions))
    after = [link["id"] for link in store.all_links()]
    if after != before:
        raise HTTPException(status_code=500, detail="整理改变了关系")
    return {"positions": positions}


@app.get("/api/media/proxy/{token}")
def media_proxy(token: str, authorization: str | None = Header(default=None)):
    require_reader(authorization)
    import json
    raw = store.setting(f"proxy:{token}")
    if not raw:
        raise HTTPException(status_code=404, detail="没有这个文件")
    try:
        saved = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=404, detail="没有这个文件") from exc
    from fastapi.responses import Response
    return Response(content=bytes.fromhex(saved["hex"]), media_type=saved["type"])


def remember_remote(url: str) -> str:
    import hashlib
    import json
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    cached = store.setting(f"proxy-url:{digest}")
    if cached:
        return cached
    payload, content_type = proxy_fetch(url)
    token = secrets.token_hex(12)
    site = f"{PUBLIC.rstrip('/')}/api/media/proxy/{token}"
    store.set_setting(f"proxy:{token}", json.dumps({"hex": payload.hex(), "type": content_type.split(";", 1)[0]}))
    store.set_setting(f"proxy-url:{digest}", site)
    return site


@app.get("/media/{bucket}/{key:path}")
def media(bucket: str, key: str, authorization: str | None = Header(default=None)):
    require_reader(authorization)
    try:
        path = local_media_path(DATA, bucket, key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="没有这个文件") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="没有这个文件")
    return FileResponse(path)


@app.get("/{path:path}")
def spa(path: str):
    page = path.strip("/")
    if page in {"", "work", "jobs", "tools", "admin", "settings", "works", "canvas", "preview"} or page.startswith("approve/"):
        index = WEB / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(_fallback_page())
    raise HTTPException(status_code=404, detail="没有这个页面")


def _fallback_page() -> str:
    return """<!doctype html><meta charset="utf-8"><title>cvgen</title>
    <body style="font-family:sans-serif;background:#111;color:#eee;padding:32px">
    <h1>cvgen</h1><p>请先登录。网页包还没有构建。</p></body>"""
