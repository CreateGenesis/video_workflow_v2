"""Exploration: works, their entity graph, compose previews, storyboard, and agent-started tasks.

Every call names its work explicitly. There is no server-side "current work".
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import db, graph
from ..auth import Principal, current_principal, need
from ..compose import compose
from ..config import get_settings
from ..engine import tasks as task_q
from ..ontology import RESOLUTIONS, document
from ..providers import adapter_for
from ..providers.instances import default_for, resolve
from .common import artifact_public, entity_public, task_public

router = APIRouter(prefix="/api", tags=["explore"])

GENERATE_KINDS = {"video", "image", "tts", "music"}
LOCAL_KINDS = {"pull": "local", "inspect": "ffmpeg", "frame": "ffmpeg", "check": "ffmpeg", "edit": "ffmpeg",
               "ffmpeg": "ffmpeg"}


class WorkIn(BaseModel):
    workspace_id: str = ""
    title: str = ""
    kind: str = ""
    brief: str = ""


class EntityIn(BaseModel):
    type: str
    data: dict = Field(default_factory=dict)
    artifact_id: str | None = None


class EntityPatch(BaseModel):
    data: dict = Field(default_factory=dict)
    merge: bool = True
    replace: bool = False
    artifact_id: str | None = None


class LinkIn(BaseModel):
    name: str
    source: str
    target: str
    note: str = ""


class LayoutIn(BaseModel):
    positions: dict[str, dict] = Field(default_factory=dict)


class PromptIn(BaseModel):
    text: str = ""
    index: int | None = None


class TaskIn(BaseModel):
    kind: str
    provider: str | None = None
    priority: int = 0
    again: bool = False
    input: dict = Field(default_factory=dict)


def _work(conn, work_id: str, principal: Principal) -> dict:
    work = graph.require_work(conn, work_id)
    principal.check_workspace(work["workspace_id"])
    return work


@router.get("/ontology")
def ontology(principal: Principal = Depends(current_principal)) -> dict:
    return document()


@router.get("/works")
def list_works(workspace_id: str = "", origin: str = "", principal: Principal = Depends(need("works:read"))) -> dict:
    with db.tx() as conn:
        items = graph.list_works(conn, workspace_id or principal.workspace_id, origin or None)
        counts = dict(conn.execute(select(db.entities.c.work_id, db.func.count()).where(
            db.entities.c.deleted_at.is_(None)).group_by(db.entities.c.work_id)).all())
    return {"items": [{**item, "entities": counts.get(item["id"], 0)} for item in items]}


@router.post("/works")
def create_work(body: WorkIn, principal: Principal = Depends(need("works:write"))) -> dict:
    with db.tx() as conn:
        if not conn.execute(select(db.workspaces.c.id).where(db.workspaces.c.id == body.workspace_id)).first():
            raise HTTPException(status_code=404, detail="没有这个工作区")
        return graph.create_work(conn, principal, body.workspace_id, body.title, kind=body.kind, brief=body.brief)


@router.get("/works/{work_id}")
def get_work(work_id: str, principal: Principal = Depends(need("works:read"))) -> dict:
    with db.tx() as conn:
        _work(conn, work_id, principal)
        snapshot = graph.snapshot(conn, work_id)
        snapshot["entities"] = [entity_public(conn, entity) for entity in snapshot["entities"]]
        for node in snapshot["assets"]:
            node["artifact"] = artifact_public(conn, node.get("artifact_id"))
        snapshot["tasks"] = [task_public(task) for task in task_q.list_tasks(conn, work_id=work_id, limit=200)]
        return snapshot


@router.patch("/works/{work_id}")
def update_work(work_id: str, body: WorkIn, principal: Principal = Depends(need("works:write"))) -> dict:
    with db.tx() as conn:
        _work(conn, work_id, principal)
        return graph.update_work(conn, principal, work_id, body.model_dump(exclude={"workspace_id"}, exclude_unset=True))


@router.delete("/works/{work_id}")
def archive_work(work_id: str, principal: Principal = Depends(need("works:write"))) -> dict:
    with db.tx() as conn:
        _work(conn, work_id, principal)
        graph.archive_work(conn, principal, work_id)
    return {"ok": True}


@router.post("/works/{work_id}/entities")
def add_entity(work_id: str, body: EntityIn, principal: Principal = Depends(need("works:write"))) -> dict:
    with db.tx() as conn:
        work = _work(conn, work_id, principal)
        if body.artifact_id:
            row = conn.execute(select(db.artifacts.c.workspace_id).where(db.artifacts.c.id == body.artifact_id)).first()
            if not row or row.workspace_id != work["workspace_id"]:
                raise HTTPException(status_code=404, detail="没有这个文件")
        entity = graph.add_entity(conn, principal, work_id, body.type, body.data, artifact_id=body.artifact_id)
        return entity_public(conn, entity)


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str, principal: Principal = Depends(need("works:read"))) -> dict:
    with db.tx() as conn:
        entity = graph.require_entity(conn, entity_id)
        _work(conn, entity["work_id"], principal)
        result = entity_public(conn, entity)
        result["links"] = graph.links_from(conn, entity_id)
        return result


@router.patch("/entities/{entity_id}")
def update_entity(entity_id: str, body: EntityPatch, principal: Principal = Depends(need("works:write"))) -> dict:
    with db.tx() as conn:
        entity = graph.require_entity(conn, entity_id)
        _work(conn, entity["work_id"], principal)
        updated = graph.update_entity(conn, principal, entity_id, body.data, merge=body.merge and not body.replace,
                                      artifact_id=body.artifact_id)
        return entity_public(conn, updated)


@router.delete("/entities/{entity_id}")
def delete_entity(entity_id: str, principal: Principal = Depends(need("works:write"))) -> dict:
    with db.tx() as conn:
        entity = graph.require_entity(conn, entity_id)
        _work(conn, entity["work_id"], principal)
        graph.delete_entity(conn, principal, entity_id)
    return {"ok": True}


@router.post("/works/{work_id}/links")
def add_link(work_id: str, body: LinkIn, principal: Principal = Depends(need("works:write"))) -> dict:
    with db.tx() as conn:
        _work(conn, work_id, principal)
        return graph.add_link(conn, principal, work_id, body.name, body.source, body.target, body.note)


@router.delete("/links/{link_id}")
def remove_link(link_id: str, principal: Principal = Depends(need("works:write"))) -> dict:
    with db.tx() as conn:
        graph.remove_link(conn, principal, link_id)
    return {"ok": True}


@router.get("/entities/{shot_id}/compose")
def compose_shot(shot_id: str, resolution: str = "768p横", principal: Principal = Depends(need("works:read"))) -> dict:
    if resolution not in RESOLUTIONS:
        raise HTTPException(status_code=400, detail=f"分辨率只能是 {'、'.join(RESOLUTIONS)}")
    with db.tx() as conn:
        entity = graph.require_entity(conn, shot_id)
        work = _work(conn, entity["work_id"], principal)
        try:
            return compose(graph.DbGraph(conn, work["workspace_id"]), shot_id, resolution)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/entities/{shot_id}/prompt")
def prompt_versions(shot_id: str, principal: Principal = Depends(need("works:read"))) -> dict:
    with db.tx() as conn:
        shot = graph.require_entity(conn, shot_id)
        _work(conn, shot["work_id"], principal)
        return {"versions": shot["data"].get("prompt_versions") or [], "action": shot["data"].get("action")}


@router.post("/entities/{shot_id}/prompt")
def save_prompt(shot_id: str, body: PromptIn, principal: Principal = Depends(need("works:write"))) -> dict:
    """Save a new action text version. index restores an older version as a new one; nothing is overwritten."""
    with db.tx() as conn:
        shot = graph.require_entity(conn, shot_id)
        _work(conn, shot["work_id"], principal)
        if shot["type"] != "Shot":
            raise HTTPException(status_code=400, detail="只有镜头有提示词版本")
        versions = list(shot["data"].get("prompt_versions") or [])
        if not versions and shot["data"].get("action"):
            versions.append({"text": shot["data"]["action"], "at": shot["created_at"].isoformat(), "by": shot["created_by"]})
        if body.index is not None:
            if not 0 <= body.index < len(versions):
                raise HTTPException(status_code=400, detail="没有这一版")
            text_value, note = versions[body.index]["text"], f"恢复第 {body.index + 1} 版"
        else:
            text_value, note = body.text.strip(), ""
        if not text_value:
            raise HTTPException(status_code=400, detail="提示词不能为空")
        versions.append({"text": text_value, "at": db.now().isoformat(), "by": f"{principal.kind}:{principal.name}",
                         "note": note})
        graph.update_entity(conn, principal, shot_id, {"prompt_versions": versions, "action": text_value})
        return {"versions": versions}


@router.post("/works/{work_id}/layout")
def save_layout(work_id: str, body: LayoutIn, principal: Principal = Depends(current_principal)) -> dict:
    """Canvas positions are a viewing preference: anyone who can read the work may move nodes."""
    principal.require("works:read")
    with db.tx() as conn:
        _work(conn, work_id, principal)
        saved = 0
        for entity_id, point in body.positions.items():
            if not isinstance(point, dict):
                continue
            position = {"x": int(point.get("x") or 0), "y": int(point.get("y") or 0)}
            saved += conn.execute(db.entities.update().where(
                db.entities.c.id == entity_id, db.entities.c.work_id == work_id,
            ).values(position=position)).rowcount
    return {"saved": saved}


@router.get("/works/{work_id}/storyboard")
def storyboard(work_id: str, resolution: str = "768p横", principal: Principal = Depends(need("works:read"))) -> dict:
    """Shots in order, each with its composed prompt, references, latest clip, checks and cost."""
    with db.tx() as conn:
        work = _work(conn, work_id, principal)
        view = graph.DbGraph(conn, work["workspace_id"])
        shots = graph.list_entities(conn, work_id, "Shot")
        work_tasks = task_q.list_tasks(conn, work_id=work_id, limit=1000)
        clips = {}
        for link in graph.list_links(conn, work_id):
            if link["name"] == "clip_of":
                clips.setdefault(link["target_id"], []).append(link["source_id"])
        rows = []
        for shot in shots:
            try:
                plan = compose(view, shot["id"], resolution)
            except ValueError as exc:
                plan = {"prompt": "", "warnings": [str(exc)], "references": [], "duration": None}
            refs = [{**ref, "artifact": artifact_public(conn, ref.get("artifact_id"))} for ref in plan["references"]]
            shot_tasks = [task for task in work_tasks
                          if (task["input"] or {}).get("shot_id") == shot["id"] or (task["input"] or {}).get("item") == shot["id"]]
            clip_entities = [graph.get_entity(conn, clip_id) for clip_id in clips.get(shot["id"], [])]
            clip_entities = [clip for clip in clip_entities if clip]
            rows.append({
                "shot": entity_public(conn, shot), "prompt": plan["prompt"], "warnings": plan["warnings"],
                "duration": plan.get("duration"), "references": refs,
                "clips": [entity_public(conn, clip) for clip in sorted(clip_entities, key=lambda c: c["created_at"], reverse=True)],
                "tasks": [task_public(task) for task in shot_tasks],
                "cost_yuan": round(sum(float((task["output"] or {}).get("cost_yuan") or 0) for task in shot_tasks), 4),
            })
        return {"work": work, "shots": rows}


def _estimate(conn, instance, kind: str, payload: dict) -> Decimal:
    request = {"duration": payload.get("duration") or 5, "n": payload.get("n") or 1, "messages": [], "system": ""}
    if kind == "video" and payload.get("shot_id"):
        shot = graph.get_entity(conn, payload["shot_id"])
        if shot:
            request["duration"] = int(shot["data"].get("duration") or 5)
    usage = adapter_for(instance).estimate(request)
    return sum((Decimal(str(instance.pricing.get(item.unit, 0))) * Decimal(str(item.quantity)) for item in usage), Decimal("0"))


def _stamp_video_request(conn, payload: dict) -> None:
    """Record the §6.5 signature before the task is ready.

    Exploration queues `{shot_id, resolution?, template?}`. Duration lives on the
    shot. prepare_video later overwrites `input.request` with the same three
    fields it submits, so a finished generate can estimate the next identical one.
    A missing duration stays unset; the timeout is not a substitute.
    """
    shot = graph.get_entity(conn, payload["shot_id"]) or {}
    data = shot.get("data") or {}
    raw = data.get("duration")
    duration = raw if raw not in (None, "") else None
    payload["request"] = {
        "template": payload.get("template") or "",
        "resolution": payload.get("resolution") or "768p横",
        "duration": duration,
    }


def _check_input(conn, work_id: str, kind: str, payload: dict) -> None:
    required = {"video": ["shot_id"], "tts": ["line_id", "voice"], "pull": ["url"], "inspect": ["entity_id"],
                "frame": ["clip_id"], "check": ["clip_id"], "edit": ["clips"], "ffmpeg": ["args"]}.get(kind, [])
    missing = [name for name in required if not payload.get(name)]
    if missing:
        raise HTTPException(status_code=400, detail=f"{kind} 缺少参数：{', '.join(missing)}")
    for key in ("shot_id", "line_id", "entity_id", "clip_id"):
        if payload.get(key):
            graph.require_entity(conn, payload[key], work_id)
    for clip_id in payload.get("clips") or []:
        graph.require_entity(conn, clip_id, work_id)


def _normalize(kind: str, payload: dict) -> dict:
    """CLI shortcuts: edit flags become ops; ffmpeg --input name=id pairs become a dict."""
    if kind == "edit" and not payload.get("ops"):
        ops = [{"op": "join", "fade_seconds": float(payload.pop("fade", 0) or 0)}]
        if payload.get("music"):
            ops.append({"op": "mix", "music": payload.pop("music"), "narration": payload.pop("narration", None)})
        if payload.get("lines"):
            ops.append({"op": "subtitle", "lines": payload.pop("lines")})
        if payload.get("export"):
            ops.append({"op": "export", "resolution": payload.pop("export")})
        payload["ops"] = ops
    for op in payload.get("ops") or []:
        if op.get("op") == "subtitle":
            lines = op.get("lines")
            if isinstance(lines, str):
                lines = [lines]
            if not isinstance(lines, list):
                raise HTTPException(status_code=400, detail="字幕要写成字符串数组，例如 [\"第一句\",\"第二句\"]")
            op["lines"] = [str(item.get("text", "")) if isinstance(item, dict) else str(item) for item in lines]
    if kind == "edit":
        for op in payload["ops"]:
            if op.get("op") == "export" and op.get("resolution") and op["resolution"] not in RESOLUTIONS:
                raise HTTPException(status_code=400, detail=f"导出分辨率只能是 {'、'.join(RESOLUTIONS)}")
    if kind == "ffmpeg" and isinstance(payload.get("inputs"), list):
        pairs = {}
        for item in payload["inputs"]:
            name, sep, artifact_id = str(item).partition("=")
            if not sep:
                raise HTTPException(status_code=400, detail=f"--input 要写成 文件名=文件id：{item}")
            pairs[name.strip()] = artifact_id.strip()
        payload["inputs"] = pairs
    return payload


@router.post("/works/{work_id}/tasks")
def create_task(work_id: str, body: TaskIn, principal: Principal = Depends(need("tasks:create"))) -> dict:
    kind = body.kind
    if kind not in GENERATE_KINDS and kind not in LOCAL_KINDS:
        raise HTTPException(status_code=400, detail=f"任务类型只能是 {', '.join(sorted(GENERATE_KINDS | set(LOCAL_KINDS)))}")
    payload = _normalize(kind, dict(body.input))
    with db.tx() as conn:
        work = _work(conn, work_id, principal)
        _check_input(conn, work_id, kind, payload)
        bonus = get_settings().exploration_priority_bonus
        common = {"workspace_id": work["workspace_id"], "kind": kind, "input": payload, "work_id": work_id,
                  "priority": body.priority + bonus, "sort_key": f"{int(db.now().timestamp() * 1000):015d}"}
        approval = None
        if kind in GENERATE_KINDS:
            instances = resolve(conn, body.provider, kind) if body.provider else default_for(conn, kind)
            if not instances:
                raise HTTPException(status_code=400, detail=f"没有配置可用的 {kind} 供应商")
            instance = instances[0]
            if kind == "video":
                existing = conn.execute(select(db.tasks.c.status).where(
                    db.tasks.c.work_id == work_id, db.tasks.c.kind == "video", db.tasks.c.superseded_by.is_(None),
                    db.tasks.c.input["shot_id"].astext == payload["shot_id"],
                )).scalars().all()
                if any(status in task_q.OPEN for status in existing):
                    raise HTTPException(status_code=409, detail="这个镜头已有未完成的生成任务，不重复提交")
                if "succeeded" in existing and not body.again:
                    raise HTTPException(status_code=409, detail="这个镜头已经成片。确实要再生成一版，请加 --again")
                _stamp_video_request(conn, payload)
            estimate = _estimate(conn, instance, kind, payload)
            threshold = Decimal(str(db.get_setting(conn, "approval_threshold_yuan", 20)))
            if principal.kind == "device" and threshold and estimate > threshold:
                approval = f"预估 {round(estimate, 2)} 元，超过审批阈值 {threshold} 元，等审计员批准后执行"
            task = task_q.create(conn, principal, pool=instance.pool, provider_instance=body.provider or instance.name,
                                 max_attempts=instance.max_attempts if instance.retry_safe else 1,
                                 retry_safe=instance.retry_safe, timeout_seconds=instance.timeout_seconds, **common)
        else:
            task = task_q.create(conn, principal, pool=LOCAL_KINDS[kind], max_attempts=2, **common)
        if approval:
            task_q.park(conn, task["id"], approval)
            task = task_q.get(conn, task["id"])
        return task_public(task)
