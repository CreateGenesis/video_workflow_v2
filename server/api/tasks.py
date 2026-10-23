"""Tasks and the queue: list, inspect, wait, cancel, resolve, retry, reprioritize."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from .. import db, events
from ..auth import Principal, need
from ..engine import tasks as task_q
from ..providers.instances import pools_overview
from .common import task_public

router = APIRouter(prefix="/api", tags=["tasks"])


class ResolveIn(BaseModel):
    action: str
    artifact_id: str | None = None


class PriorityIn(BaseModel):
    priority: int


def _task(conn, task_id: str, principal: Principal) -> dict:
    task = task_q.get(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="没有这个任务")
    principal.check_workspace(task["workspace_id"])
    return task


@router.get("/tasks")
def list_tasks(work_id: str = "", run_id: str = "", status: str = "", pool: str = "", limit: int = 100,
               principal: Principal = Depends(need("queue:read"))) -> dict:
    statuses = [item for item in status.split(",") if item] or None
    with db.tx() as conn:
        rows = task_q.list_tasks(conn, workspace_id=principal.workspace_id, run_id=run_id or None,
                                 work_id=work_id or None, statuses=statuses, pool=pool or None, limit=min(limit, 500))
    return {"items": [task_public(row) for row in rows]}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, principal: Principal = Depends(need("queue:read"))) -> dict:
    with db.tx() as conn:
        task = _task(conn, task_id, principal)
        data = task_public(task, full=True)
        data["queue_position"] = task_q.queue_position(conn, task)
        data["depends_on"] = task_q.deps_of(conn, task_id)
        return data


def _snapshot(task_id: str, principal: Principal) -> tuple[dict, int | None]:
    with db.tx() as conn:
        task = _task(conn, task_id, principal)
        return task, task_q.queue_position(conn, task)


@router.get("/tasks/{task_id}/wait")
async def wait_task(task_id: str, timeout: int = 55, principal: Principal = Depends(need("queue:read"))) -> dict:
    """Long poll: returns as soon as the task ends or needs a person, or after `timeout` seconds."""
    deadline = asyncio.get_running_loop().time() + max(1, min(timeout, 120))
    while True:
        task, position = await asyncio.to_thread(_snapshot, task_id, principal)
        if task["status"] in task_q.TERMINAL or task["status"] in {"needs_attention", "waiting"}:
            return {**task_public(task), "done": task["status"] in task_q.TERMINAL}
        if asyncio.get_running_loop().time() >= deadline:
            return {**task_public(task), "done": False, "queue_position": position}
        await asyncio.sleep(1.0)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, principal: Principal = Depends(need("queue:read"))) -> dict:
    with db.tx() as conn:
        task = _task(conn, task_id, principal)
        own = task["created_by_kind"] == principal.kind and task["created_by_id"] == principal.id
        if not own and not principal.can("queue:manage") and not principal.can("works:write"):
            raise HTTPException(status_code=403, detail="只能取消自己发起的任务")
        if task.get("run_id"):
            conn.execute(select(db.runs.c.id).where(db.runs.c.id == task["run_id"]).with_for_update())
        task = task_q.request_cancel(conn, principal, task_id)
        if task.get("run_id"):
            from ..workflows.runner import advance

            advance(conn, task["run_id"], principal)
        return task_public(task)


@router.post("/tasks/{task_id}/resolve")
def resolve_task(task_id: str, body: ResolveIn, principal: Principal = Depends(need("queue:read"))) -> dict:
    needed = {"approve": "workflows:publish", "requery": "tasks:resolve", "fail": "tasks:resolve",
              "resubmit": "tasks:resolve", "attach": "tasks:resolve"}.get(body.action)
    if not needed:
        raise HTTPException(status_code=400, detail="动作只能是 approve、requery、fail、resubmit、attach")
    principal.require(needed)
    with db.tx() as conn:
        current = _task(conn, task_id, principal)
        if current.get("run_id"):
            conn.execute(select(db.runs.c.id).where(db.runs.c.id == current["run_id"]).with_for_update())
        try:
            task = task_q.resolve_attention(conn, principal, task_id, body.action, body.artifact_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if task.get("run_id"):
            from ..workflows.runner import advance

            advance(conn, task["run_id"], principal)
        return task_public(task)


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: str, principal: Principal = Depends(need("queue:read"))) -> dict:
    """A failed or canceled exploration task runs again as a new task. Runs use rerun instead."""
    with db.tx() as conn:
        task = _task(conn, task_id, principal)
        if task.get("run_id"):
            raise HTTPException(status_code=400, detail="运行里的任务请用“重跑这一条”")
        if task["status"] not in {"failed", "canceled"}:
            raise HTTPException(status_code=409, detail="只有失败或取消的任务可以重试")
        if not (principal.can("tasks:create") and (task["created_by_id"] == principal.id or principal.can("queue:manage"))):
            raise HTTPException(status_code=403, detail="没有权限重试这个任务")
        fresh = task_q.supersede(conn, principal, task_id, input_patch={"retried_from": task_id})
        events.record(conn, principal, "task.retry", workspace_id=task["workspace_id"], work_id=task["work_id"],
                      target_kind=task["kind"], target_id=fresh["id"], payload={"from": task_id})
        return task_public(fresh)


@router.post("/tasks/{task_id}/priority")
def reprioritize(task_id: str, body: PriorityIn, principal: Principal = Depends(need("queue:manage"))) -> dict:
    with db.tx() as conn:
        task = _task(conn, task_id, principal)
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(priority=body.priority))
        events.record(conn, principal, "task.priority", workspace_id=task["workspace_id"], run_id=task["run_id"],
                      target_kind=task["kind"], target_id=task_id, payload={"priority": body.priority})
        db.notify(conn, "cvgen_tasks", task["pool"])
        return task_public(task_q.get(conn, task_id))


@router.get("/queue")
def queue(principal: Principal = Depends(need("queue:read"))) -> dict:
    with db.tx() as conn:
        pools = pools_overview(conn)
        active = task_q.list_tasks(conn, workspace_id=principal.workspace_id,
                                   statuses=["leased", "running", "submitting", "submitted"], limit=200)
        ready = conn.execute(select(db.tasks).where(db.tasks.c.status == "ready").order_by(
            db.tasks.c.pool, db.tasks.c.priority.desc(), db.tasks.c.sort_key, db.tasks.c.created_at,
        ).limit(300)).mappings().all()
        attention = task_q.list_tasks(conn, workspace_id=principal.workspace_id,
                                      statuses=["needs_attention", "waiting"], limit=200)
        instances = conn.execute(select(db.provider_instances.c.name, db.provider_instances.c.pool,
                                        db.provider_instances.c.protocol, db.provider_instances.c.health,
                                        db.provider_instances.c.enabled)).mappings().all()
    return {
        "pools": pools,
        "active": [task_public(task) for task in active],
        "ready": [task_public(dict(task)) for task in ready],
        "attention": [task_public(task) for task in attention],
        "instances": [dict(row) for row in instances],
    }
