"""Workflows (versioned JSON specs) and their runs."""

from __future__ import annotations

import difflib
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select, update

from .. import db, events
from ..auth import Principal, need
from ..engine import tasks as task_q
from ..workflows import runner
from ..workflows.dryrun import compile_run
from ..workflows.spec import analyze, semantic_check, structure_errors
from .common import number, task_public, with_urls

router = APIRouter(prefix="/api", tags=["workflows"])


class DraftIn(BaseModel):
    workspace_id: str = ""
    name: str = ""
    spec: dict
    notes: str = ""
    source_work_id: str | None = None


class VersionPatch(BaseModel):
    spec: dict | None = None
    notes: str | None = None
    fixtures: dict | None = None


class DryRunIn(BaseModel):
    inputs: dict = Field(default_factory=dict)
    level: str = "compile"


class RunIn(BaseModel):
    workflow_id: str
    version: int | None = None
    inputs: dict = Field(default_factory=dict)
    priority: int = 0
    auto_gates: bool = False
    callback_url: str = ""
    idempotency_key: str | None = None


class BatchIn(BaseModel):
    workflow_id: str
    version: int | None = None
    inputs: list[dict]
    priority: int = 0
    auto_gates: bool = False
    callback_url: str = ""


class GateIn(BaseModel):
    decision: str
    note: str = ""
    selections: dict = Field(default_factory=dict)
    redo: list[str] = Field(default_factory=list)


class RerunIn(BaseModel):
    node: str
    item: str = ""


class FixturesFromRun(BaseModel):
    run_id: str


def _workflow(conn, workflow_id: str, principal: Principal) -> dict:
    row = conn.execute(select(db.workflows).where(db.workflows.c.id == workflow_id)).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="没有这个工作流")
    principal.check_workspace(row["workspace_id"])
    return dict(row)


def _version(conn, workflow_id: str, version: int) -> dict:
    row = conn.execute(select(db.workflow_versions).where(
        db.workflow_versions.c.workflow_id == workflow_id, db.workflow_versions.c.version == version,
    )).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="没有这个版本")
    return dict(row)


def _validate(conn, workspace_id: str, spec: dict, check_env: bool = False) -> dict:
    errors = structure_errors(spec)
    if errors:
        return {"errors": errors, "warnings": [], "order": []}
    return semantic_check(conn, workspace_id, spec, check_env=check_env)


def _summary(conn, workflow: dict) -> dict:
    versions = conn.execute(select(
        db.workflow_versions.c.version, db.workflow_versions.c.status, db.workflow_versions.c.created_at,
        db.workflow_versions.c.created_by, db.workflow_versions.c.published_at, db.workflow_versions.c.published_by,
        db.workflow_versions.c.notes, db.workflow_versions.c.validation, db.workflow_versions.c.source_work_id,
    ).where(db.workflow_versions.c.workflow_id == workflow["id"]).order_by(db.workflow_versions.c.version.desc())).mappings().all()
    versions = [{**dict(row), "errors": len((row["validation"] or {}).get("errors", [])),
                 "warnings": len((row["validation"] or {}).get("warnings", []))} for row in versions]
    for row in versions:
        row.pop("validation")
    published = next((row for row in versions if row["status"] == "published"), None)
    runs = conn.execute(select(func.count(), func.avg(db.runs.c.cost_actual)).where(
        db.runs.c.workflow_id == workflow["id"], db.runs.c.mode == "production",
    )).first()
    return {**workflow, "versions": versions, "published_version": published["version"] if published else None,
            "description": None, "runs": runs[0], "avg_cost_yuan": number(runs[1]) if runs[1] else None}


@router.get("/workflows")
def list_workflows(workspace_id: str = "", principal: Principal = Depends(need("workflows:read"))) -> dict:
    with db.tx() as conn:
        query = select(db.workflows).where(db.workflows.c.archived.is_(False)).order_by(db.workflows.c.name)
        scope = workspace_id or principal.workspace_id
        if scope:
            query = query.where(db.workflows.c.workspace_id == scope)
        items = []
        for row in conn.execute(query).mappings():
            summary = _summary(conn, dict(row))
            if principal.kind == "apikey" and not summary["published_version"]:
                continue
            latest = _version(conn, row["id"], summary["published_version"] or summary["versions"][0]["version"]) \
                if summary["versions"] else None
            summary["description"] = (latest or {}).get("spec", {}).get("description")
            items.append(summary)
        return {"items": items}


@router.post("/workflows")
def create_draft(body: DraftIn, principal: Principal = Depends(need("workflows:draft"))) -> dict:
    """Create the workflow on first use (by name) and add a new draft version."""
    name = (body.name or body.spec.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="工作流需要名称")
    with db.tx() as conn:
        if not conn.execute(select(db.workspaces.c.id).where(db.workspaces.c.id == body.workspace_id)).first():
            raise HTTPException(status_code=404, detail="没有这个工作区")
        row = conn.execute(select(db.workflows).where(db.workflows.c.workspace_id == body.workspace_id,
                                                      db.workflows.c.name == name)).mappings().first()
        if row:
            workflow_id = row["id"]
        else:
            workflow_id = db.new_id("wf")
            conn.execute(insert(db.workflows).values(id=workflow_id, workspace_id=body.workspace_id, name=name,
                                                     created_by=f"{principal.kind}:{principal.id}"))
        return _new_version(conn, principal, workflow_id, body.workspace_id, body.spec, body.notes, body.source_work_id)


def _new_version(conn, principal, workflow_id: str, workspace_id: str, spec: dict, notes: str, source_work_id) -> dict:
    version = conn.execute(select(func.coalesce(func.max(db.workflow_versions.c.version), 0) + 1)
                           .where(db.workflow_versions.c.workflow_id == workflow_id)).scalar_one()
    previous = conn.execute(select(db.workflow_versions.c.fixtures).where(db.workflow_versions.c.workflow_id == workflow_id)
                            .order_by(db.workflow_versions.c.version.desc()).limit(1)).scalar()
    validation = _validate(conn, workspace_id, spec)
    conn.execute(insert(db.workflow_versions).values(
        workflow_id=workflow_id, version=version, spec=spec, status="draft", notes=notes or "",
        source_work_id=source_work_id, validation=validation, fixtures=previous or {},
        created_by=f"{principal.kind}:{principal.name}",
    ))
    events.record(conn, principal, "workflow.draft", workspace_id=workspace_id, target_kind="workflow",
                  target_id=f"{workflow_id}@{version}", payload={"errors": len(validation["errors"])})
    return {"workflow_id": workflow_id, "version": version, "validation": validation}


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, principal: Principal = Depends(need("workflows:read"))) -> dict:
    with db.tx() as conn:
        return _summary(conn, _workflow(conn, workflow_id, principal))


@router.get("/workflows/{workflow_id}/versions/{version}")
def get_version(workflow_id: str, version: int, principal: Principal = Depends(need("workflows:read"))) -> dict:
    with db.tx() as conn:
        _workflow(conn, workflow_id, principal)
        row = _version(conn, workflow_id, version)
        if principal.kind == "apikey" and row["status"] != "published":
            raise HTTPException(status_code=404, detail="没有这个版本")
        analysis = analyze(row["spec"])
        row["graph"] = {"order": analysis.order, "deps": {key: sorted(value) for key, value in analysis.deps.items()}}
        return row


@router.post("/workflows/{workflow_id}/versions")
def add_version(workflow_id: str, body: DraftIn, principal: Principal = Depends(need("workflows:draft"))) -> dict:
    with db.tx() as conn:
        workflow = _workflow(conn, workflow_id, principal)
        return _new_version(conn, principal, workflow_id, workflow["workspace_id"], body.spec, body.notes, body.source_work_id)


@router.put("/workflows/{workflow_id}/versions/{version}")
def edit_version(workflow_id: str, version: int, body: VersionPatch,
                 principal: Principal = Depends(need("workflows:draft"))) -> dict:
    with db.tx() as conn:
        workflow = _workflow(conn, workflow_id, principal)
        row = _version(conn, workflow_id, version)
        values: dict = {"updated_at": db.now()}
        if body.spec is not None or body.notes is not None:
            if row["status"] != "draft":
                raise HTTPException(status_code=409, detail="已发布的版本不能修改，请新建一个版本")
            if body.spec is not None:
                values["spec"] = body.spec
                values["validation"] = _validate(conn, workflow["workspace_id"], body.spec)
            if body.notes is not None:
                values["notes"] = body.notes
        if body.fixtures is not None:
            values["fixtures"] = body.fixtures
        conn.execute(update(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id,
                                                        db.workflow_versions.c.version == version).values(**values))
        events.record(conn, principal, "workflow.edit", workspace_id=workflow["workspace_id"], target_kind="workflow",
                      target_id=f"{workflow_id}@{version}", payload={"fields": sorted(k for k in values if k != "updated_at")})
        return _version(conn, workflow_id, version)


@router.post("/workflows/{workflow_id}/versions/{version}/validate")
def validate(workflow_id: str, version: int, check_env: bool = False,
             principal: Principal = Depends(need("workflows:read"))) -> dict:
    with db.tx() as conn:
        workflow = _workflow(conn, workflow_id, principal)
        row = _version(conn, workflow_id, version)
        result = _validate(conn, workflow["workspace_id"], row["spec"], check_env=check_env)
        if row["status"] == "draft":
            conn.execute(update(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id,
                                                            db.workflow_versions.c.version == version).values(validation=result))
        return result


@router.post("/workflows/{workflow_id}/versions/{version}/dry-run")
def dry_run(workflow_id: str, version: int, body: DryRunIn, principal: Principal = Depends(need("workflows:read"))) -> dict:
    with db.tx() as conn:
        workflow = _workflow(conn, workflow_id, principal)
        row = _version(conn, workflow_id, version)
        problems = structure_errors(row["spec"]) + runner.input_errors(row["spec"], body.inputs)
        if problems:
            raise HTTPException(status_code=400, detail="；".join(problems))
        if body.level == "compile":
            return {"level": "compile", **compile_run(conn, workflow["workspace_id"], row["spec"], body.inputs, row["fixtures"] or {})}
        if body.level == "llm":
            if not (principal.can("runs:create") or principal.can("runs:create:trial")):
                raise HTTPException(status_code=403, detail="没有权限发起试跑")
            run = runner.create_run(conn, principal, workflow_id=workflow_id, version=version, inputs=body.inputs,
                                    mode="dryrun-llm")
            return {"level": "llm", "run_id": run["id"], "status": run["status"],
                    "message": "大模型步骤已排队。运行结束后 outputs.compiled 里是全部提示词和估算"}
        raise HTTPException(status_code=400, detail="level 只能是 compile 或 llm")


@router.post("/workflows/{workflow_id}/versions/{version}/trial")
def trial(workflow_id: str, version: int, body: DryRunIn, principal: Principal = Depends(need("workflows:read"))) -> dict:
    if not (principal.can("runs:create") or principal.can("runs:create:trial")):
        raise HTTPException(status_code=403, detail="没有权限发起试跑")
    with db.tx() as conn:
        _workflow(conn, workflow_id, principal)
        return _run_view(conn, runner.create_run(conn, principal, workflow_id=workflow_id, version=version,
                                                  inputs=body.inputs, mode="trial"))


@router.post("/workflows/{workflow_id}/versions/{version}/fixtures-from-run")
def fixtures_from_run(workflow_id: str, version: int, body: FixturesFromRun,
                      principal: Principal = Depends(need("workflows:draft"))) -> dict:
    with db.tx() as conn:
        _workflow(conn, workflow_id, principal)
        row = _version(conn, workflow_id, version)
        run = runner.get_run(conn, body.run_id)
        if not run or run["workflow_id"] != workflow_id:
            raise HTTPException(status_code=404, detail="这个运行不属于这个工作流")
        fixtures = dict(row["fixtures"] or {})
        for task in runner.current_tasks(conn, run["id"]):
            if task["kind"] == "llm" and task["status"] == "succeeded":
                fixtures[task["node_id"]] = (task["output"] or {}).get("json")
        conn.execute(update(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id,
                                                        db.workflow_versions.c.version == version).values(fixtures=fixtures))
        return {"fixtures": fixtures}


@router.post("/workflows/{workflow_id}/versions/{version}/publish")
def publish(workflow_id: str, version: int, principal: Principal = Depends(need("workflows:publish"))) -> dict:
    if principal.kind != "user":
        raise HTTPException(status_code=403, detail="只有人可以发布工作流")
    with db.tx() as conn:
        workflow = _workflow(conn, workflow_id, principal)
        row = _version(conn, workflow_id, version)
        if row["status"] == "published":
            return row
        result = _validate(conn, workflow["workspace_id"], row["spec"])
        if result["errors"]:
            raise HTTPException(status_code=409, detail="校验没有通过，不能发布：" + "；".join(result["errors"][:5]))
        conn.execute(update(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id,
                                                        db.workflow_versions.c.version == version).values(
            status="published", validation=result, published_by=principal.name, published_at=db.now()))
        events.record(conn, principal, "workflow.publish", workspace_id=workflow["workspace_id"], target_kind="workflow",
                      target_id=f"{workflow_id}@{version}", payload={"name": workflow["name"]})
        return _version(conn, workflow_id, version)


@router.post("/workflows/{workflow_id}/versions/{version}/retire")
def retire(workflow_id: str, version: int, principal: Principal = Depends(need("workflows:publish"))) -> dict:
    with db.tx() as conn:
        workflow = _workflow(conn, workflow_id, principal)
        conn.execute(update(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id,
                                                        db.workflow_versions.c.version == version).values(status="retired"))
        events.record(conn, principal, "workflow.retire", workspace_id=workflow["workspace_id"], target_kind="workflow",
                      target_id=f"{workflow_id}@{version}")
        return _version(conn, workflow_id, version)


@router.get("/workflows/{workflow_id}/diff")
def diff(workflow_id: str, base: int, head: int, principal: Principal = Depends(need("workflows:read"))) -> dict:
    with db.tx() as conn:
        _workflow(conn, workflow_id, principal)
        old = json.dumps(_version(conn, workflow_id, base)["spec"], ensure_ascii=False, indent=2, sort_keys=True)
        new = json.dumps(_version(conn, workflow_id, head)["spec"], ensure_ascii=False, indent=2, sort_keys=True)
    lines = difflib.unified_diff(old.splitlines(), new.splitlines(), f"v{base}", f"v{head}", lineterm="")
    return {"diff": "\n".join(lines)}


def _run_view(conn, run: dict, detail: bool = False) -> dict:
    workflow = conn.execute(select(db.workflows.c.name).where(db.workflows.c.id == run["workflow_id"])).scalar()
    data = {key: number(value) for key, value in run.items() if key not in {"context"}}
    data["workflow_name"] = workflow
    data["outputs"] = with_urls(run.get("outputs") or {})
    tasks = runner.current_tasks(conn, run["id"])
    from ..engine.eta import run_eta_seconds

    data["progress"] = {
        "total": len(tasks), "succeeded": sum(task["status"] == "succeeded" for task in tasks),
        "active": sum(task["status"] in ("leased", "running", "submitting", "submitted") for task in tasks),
        "waiting": sum(task["status"] in ("waiting", "needs_attention") for task in tasks),
        "ready": sum(task["status"] == "ready" for task in tasks),
        "eta_seconds": run_eta_seconds(conn, tasks),
    }
    if detail:
        spec = runner.get_version(conn, run["workflow_id"], run["version"], published_only=False)["spec"]
        analysis = analyze(spec)
        by_node: dict[str, list] = {}
        for task in tasks:
            by_node.setdefault(task["node_id"], []).append(task_public(task))
        data["nodes"] = [{"id": node_id, "kind": analysis.nodes[node_id]["kind"],
                          "title": analysis.nodes[node_id].get("title") or node_id,
                          "for_each": analysis.nodes[node_id].get("for_each"), "tasks": by_node.get(node_id, [])}
                         for node_id in analysis.order]
        data["spec"] = spec
        costs = conn.execute(select(db.cost_ledger.c.provider_instance, db.cost_ledger.c.unit,
                                    func.sum(db.cost_ledger.c.quantity), func.sum(db.cost_ledger.c.amount_yuan))
                             .where(db.cost_ledger.c.run_id == run["id"])
                             .group_by(db.cost_ledger.c.provider_instance, db.cost_ledger.c.unit)).all()
        data["costs"] = [{"provider": row[0], "unit": row[1], "quantity": number(row[2]), "yuan": number(row[3])} for row in costs]
    return data


@router.post("/runs")
def start_run(body: RunIn, principal: Principal = Depends(need("runs:create"))) -> dict:
    with db.tx() as conn:
        run = runner.create_run(conn, principal, workflow_id=body.workflow_id, version=body.version, inputs=body.inputs,
                                priority=body.priority, auto_gates=body.auto_gates, callback_url=body.callback_url,
                                idempotency_key=body.idempotency_key)
        return _run_view(conn, run)


@router.post("/batches")
def start_batch(body: BatchIn, principal: Principal = Depends(need("runs:create"))) -> dict:
    if not body.inputs or len(body.inputs) > 200:
        raise HTTPException(status_code=400, detail="一批 1 到 200 组输入")
    with db.tx() as conn:
        version = runner.get_version(conn, body.workflow_id, body.version)
        principal.check_workspace(version["workspace_id"])
        problems = [f"第 {index + 1} 组：{problem}" for index, inputs in enumerate(body.inputs)
                    for problem in runner.input_errors(version["spec"], inputs)]
        if problems:
            raise HTTPException(status_code=400, detail="；".join(problems[:10]))
        batch_id = db.new_id("batch")
        conn.execute(insert(db.batches).values(id=batch_id, workspace_id=version["workspace_id"],
                                               workflow_id=body.workflow_id, version=version["version"],
                                               size=len(body.inputs), created_by_kind=principal.kind,
                                               created_by_id=principal.id))
        runs = [runner.create_run(conn, principal, workflow_id=body.workflow_id, version=version["version"],
                                  inputs=inputs, priority=body.priority, batch_id=batch_id, auto_gates=body.auto_gates,
                                  callback_url=body.callback_url) for inputs in body.inputs]
        return {"batch_id": batch_id, "runs": [_run_view(conn, run) for run in runs]}


@router.get("/runs")
def list_runs(workspace_id: str = "", status: str = "", workflow_id: str = "", batch_id: str = "", mode: str = "",
              limit: int = 100, principal: Principal = Depends(need("runs:read"))) -> dict:
    with db.tx() as conn:
        query = select(db.runs).order_by(db.runs.c.created_at.desc()).limit(min(limit, 500))
        scope = workspace_id or principal.workspace_id
        if scope:
            query = query.where(db.runs.c.workspace_id == scope)
        if principal.kind == "apikey":
            query = query.where(db.runs.c.created_by_kind == "apikey", db.runs.c.created_by_id == principal.id)
        if status:
            query = query.where(db.runs.c.status.in_(status.split(",")))
        if workflow_id:
            query = query.where(db.runs.c.workflow_id == workflow_id)
        if batch_id:
            query = query.where(db.runs.c.batch_id == batch_id)
        if mode:
            query = query.where(db.runs.c.mode == mode)
        return {"items": [_run_view(conn, dict(row)) for row in conn.execute(query).mappings()]}


def _run(conn, run_id: str, principal: Principal) -> dict:
    run = runner.get_run(conn, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="没有这个运行")
    principal.check_workspace(run["workspace_id"])
    if principal.kind == "apikey" and run["created_by_id"] != principal.id:
        raise HTTPException(status_code=404, detail="没有这个运行")
    return run


@router.get("/runs/{run_id}")
def get_run(run_id: str, principal: Principal = Depends(need("runs:read"))) -> dict:
    with db.tx() as conn:
        return _run_view(conn, _run(conn, run_id, principal), detail=True)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, principal: Principal = Depends(need("runs:read"))) -> dict:
    with db.tx() as conn:
        run = _run(conn, run_id, principal)
        if not (principal.can("runs:create") or run["created_by_id"] == principal.id):
            raise HTTPException(status_code=403, detail="没有权限取消这个运行")
        return _run_view(conn, runner.cancel_run(conn, principal, run_id))


@router.post("/runs/{run_id}/pause")
def pause(run_id: str, principal: Principal = Depends(need("runs:create"))) -> dict:
    with db.tx() as conn:
        _run(conn, run_id, principal)
        return _run_view(conn, runner.set_paused(conn, principal, run_id, True))


@router.post("/runs/{run_id}/resume")
def resume(run_id: str, principal: Principal = Depends(need("runs:create"))) -> dict:
    with db.tx() as conn:
        _run(conn, run_id, principal)
        return _run_view(conn, runner.set_paused(conn, principal, run_id, False))


@router.post("/runs/{run_id}/rerun")
def rerun(run_id: str, body: RerunIn, principal: Principal = Depends(need("runs:create"))) -> dict:
    with db.tx() as conn:
        _run(conn, run_id, principal)
        created = runner.rerun_item(conn, principal, run_id, body.node, body.item)
        return {"created": created, "run": _run_view(conn, runner.get_run(conn, run_id))}


@router.post("/gates/{task_id}")
def decide(task_id: str, body: GateIn, principal: Principal = Depends(need("runs:read"))) -> dict:
    with db.tx() as conn:
        task = task_q.get(conn, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="没有这个闸门")
        _run(conn, task["run_id"], principal)
        return task_public(runner.decide_gate(conn, principal, task_id, body.decision, note=body.note,
                                              selections=body.selections, redo=body.redo))
