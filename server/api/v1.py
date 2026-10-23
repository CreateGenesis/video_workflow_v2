"""Service API v1 for other systems. API keys are bound to one workspace and see only published workflows.

Callbacks: when a run has callback_url, cvgen POSTs {event, run_id, status, ...} with headers
X-CVGEN-Event, X-CVGEN-Timestamp and X-CVGEN-Signature: sha256=HMAC_SHA256(secret, "<timestamp>.<body>").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import db
from ..auth import Principal, need
from ..security import media_url
from . import library, workflows

router = APIRouter(prefix="/v1", tags=["service-api-v1"])


class RunCreate(BaseModel):
    workflow_id: str
    version: int | None = Field(default=None, description="省略时用最新发布版本")
    inputs: dict = Field(default_factory=dict)
    priority: int = 0
    callback_url: str = ""


class BatchCreate(BaseModel):
    workflow_id: str
    version: int | None = None
    inputs: list[dict]
    priority: int = 0
    callback_url: str = ""


def _brief(run: dict) -> dict:
    keys = ("id", "status", "workflow_id", "workflow_name", "version", "batch_id", "inputs", "priority", "progress",
            "cost_estimate", "cost_actual", "error", "created_at", "started_at", "finished_at")
    return {key: run.get(key) for key in keys}


@router.get("/workflows")
def list_workflows(principal: Principal = Depends(need("workflows:read"))) -> dict:
    items = workflows.list_workflows(workspace_id="", principal=principal)["items"]
    return {"items": [{"id": item["id"], "name": item["name"], "description": item["description"],
                       "version": item["published_version"]} for item in items if item["published_version"]]}


@router.get("/workflows/{workflow_id}/versions/{version}")
def workflow_version(workflow_id: str, version: int, principal: Principal = Depends(need("workflows:read"))) -> dict:
    row = workflows.get_version(workflow_id, version, principal)
    if row["status"] != "published":
        raise HTTPException(status_code=404, detail="没有这个版本")
    return {"workflow_id": workflow_id, "version": version, "name": row["spec"].get("name"),
            "description": row["spec"].get("description"), "inputs": row["spec"].get("inputs"),
            "outputs": list((row["spec"].get("outputs") or {}).keys()), "budget": row["spec"].get("budget")}


@router.post("/assets/uploads")
def upload(file: UploadFile = File(...), label: str = Form(""), principal: Principal = Depends(need("uploads:write"))) -> dict:
    if not principal.workspace_id:
        raise HTTPException(status_code=400, detail="服务 API 需要绑定工作区的 API 密钥")
    return library.upload(file=file, workspace_id=principal.workspace_id, label=label, principal=principal)


@router.post("/runs", status_code=202)
def create_run(body: RunCreate, idempotency_key: str | None = Header(default=None),
               principal: Principal = Depends(need("runs:create"))) -> dict:
    run = workflows.start_run(workflows.RunIn(
        workflow_id=body.workflow_id, version=body.version, inputs=body.inputs, priority=body.priority,
        callback_url=body.callback_url, idempotency_key=idempotency_key,
    ), principal)
    return _brief(run)


@router.post("/batches", status_code=202)
def create_batch(body: BatchCreate, principal: Principal = Depends(need("runs:create"))) -> dict:
    result = workflows.start_batch(workflows.BatchIn(
        workflow_id=body.workflow_id, version=body.version, inputs=body.inputs, priority=body.priority,
        callback_url=body.callback_url,
    ), principal)
    return {"batch_id": result["batch_id"], "runs": [_brief(run) for run in result["runs"]]}


@router.get("/runs")
def list_runs(status: str = "", batch_id: str = "", limit: int = 50, principal: Principal = Depends(need("runs:read"))) -> dict:
    items = workflows.list_runs(status=status, batch_id=batch_id, limit=limit, principal=principal)["items"]
    return {"items": [_brief(run) for run in items]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, principal: Principal = Depends(need("runs:read"))) -> dict:
    run = workflows.get_run(run_id, principal)
    stages = [{"node": node["id"], "kind": node["kind"], "total": len(node["tasks"]),
               "done": sum(task["status"] == "succeeded" for task in node["tasks"])} for node in run["nodes"]]
    return {**_brief(run), "stages": stages}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str, principal: Principal = Depends(need("runs:read"))) -> dict:
    return _brief(workflows.cancel(run_id, principal))


@router.post("/runs/{run_id}/items/{node_id}/{item}/rerun", status_code=202)
def rerun(run_id: str, node_id: str, item: str, principal: Principal = Depends(need("runs:create"))) -> dict:
    result = workflows.rerun(run_id, workflows.RerunIn(node=node_id, item=item), principal)
    return {"created": result["created"], "run": _brief(result["run"])}


@router.get("/runs/{run_id}/outputs")
def outputs(run_id: str, principal: Principal = Depends(need("runs:read"))) -> dict:
    with db.tx() as conn:
        run = workflows._run(conn, run_id, principal)
    if run["status"] != "succeeded":
        raise HTTPException(status_code=409, detail=f"运行还没有成功结束（{run['status']}）")
    result = {}
    for name, items in (run["outputs"] or {}).items():
        if name.startswith("_"):
            continue
        result[name] = [{"item": item.get("item"), "artifact_id": item.get("artifact_id"),
                         "url": media_url(item.get("artifact_id"), absolute=True) if item.get("artifact_id") else None}
                        for item in items]
    return {"run_id": run_id, "outputs": result, "flags": (run["outputs"] or {}).get("_flags", [])}
