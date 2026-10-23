"""Task queue on PostgreSQL.

States:
  blocked ─deps done─▶ ready ─claim─▶ leased ─┬─ sync:  running ──▶ succeeded | failed
                                              └─ async: submitting ──▶ submitted ──▶ succeeded | failed
  gate tasks: blocked ─deps done─▶ waiting ─decision─▶ succeeded | failed
  any open state ─cancel─▶ canceled;  needs_attention waits for a person.

A task holds one slot of its pool from claim until it ends, including while an upstream job runs.
Expired leases are recovered by the janitor; a submitted task is resumed by polling its provider
reference and is never submitted twice.
"""

from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import and_, func, insert, select, text, update
from sqlalchemy.engine import Connection

from .. import db, events

LEASE_SECONDS = 60
ACTIVE = ("leased", "running", "submitting", "submitted")
TERMINAL = ("succeeded", "failed", "canceled")
OPEN = ("blocked", "ready", "waiting", "needs_attention", *ACTIVE)
GATE_POOL = "gate"


def _row(conn: Connection, task_id: str, lock: bool = False) -> dict | None:
    query = select(db.tasks).where(db.tasks.c.id == task_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).mappings().first()
    return dict(row) if row else None


def get(conn: Connection, task_id: str) -> dict | None:
    return _row(conn, task_id)


def deps_of(conn: Connection, task_id: str) -> list[str]:
    return list(conn.execute(select(db.task_deps.c.depends_on).where(db.task_deps.c.task_id == task_id)).scalars())


def _deps_done(conn: Connection, task_id: str) -> bool:
    pending = conn.execute(
        select(func.count()).select_from(db.task_deps.join(db.tasks, db.tasks.c.id == db.task_deps.c.depends_on))
        .where(db.task_deps.c.task_id == task_id, db.tasks.c.status != "succeeded")
    ).scalar_one()
    return pending == 0


def create(
    conn: Connection,
    principal,
    *,
    workspace_id: str,
    kind: str,
    pool: str,
    input: dict,
    run_id: str | None = None,
    work_id: str | None = None,
    node_id: str | None = None,
    item_key: str = "",
    item_index: int = 0,
    provider_instance: str | None = None,
    priority: int = 0,
    sort_key: str = "",
    max_attempts: int = 1,
    backoff_seconds: int = 30,
    timeout_seconds: int = 1800,
    retry_safe: bool = True,
    depends_on: list[str] | tuple[str, ...] = (),
) -> dict:
    task_id = db.new_id("task")
    conn.execute(insert(db.tasks).values(
        id=task_id, workspace_id=workspace_id, run_id=run_id, work_id=work_id, node_id=node_id,
        item_key=item_key, item_index=item_index, kind=kind, provider_instance=provider_instance, pool=pool,
        status="blocked", priority=priority, sort_key=sort_key, max_attempts=max(1, max_attempts),
        backoff_seconds=backoff_seconds, timeout_seconds=timeout_seconds, retry_safe=retry_safe, input=input,
        created_by_kind=principal.kind, created_by_id=principal.id,
    ))
    for dep in dict.fromkeys(depends_on):
        conn.execute(insert(db.task_deps).values(task_id=task_id, depends_on=dep))
    if _deps_done(conn, task_id):
        _open(conn, task_id)
    events.record(conn, principal, "task.create", workspace_id=workspace_id, work_id=work_id, run_id=run_id,
                  target_kind=kind, target_id=task_id, payload={"pool": pool, "node": node_id, "item": item_key})
    return _row(conn, task_id)


def _open(conn: Connection, task_id: str) -> list[str]:
    """Dependencies are done: make the task runnable (or a gate waitable). Returns tasks that changed."""
    task = _row(conn, task_id)
    if task["status"] != "blocked":
        return []
    if task["kind"] == "gate":
        if (task["input"] or {}).get("auto_approve"):
            conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
                status="succeeded", finished_at=db.now(), output={"decision": "approved", "auto": True},
            ))
            return [task_id, *unblock_dependents(conn, task_id)]
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(status="waiting", ready_at=db.now()))
        db.notify(conn, "cvgen_events", task["run_id"] or "")
        return [task_id]
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(status="ready", ready_at=db.now()))
    db.notify(conn, "cvgen_tasks", task["pool"])
    return [task_id]


def unblock_dependents(conn: Connection, task_id: str) -> list[str]:
    changed = []
    dependents = conn.execute(select(db.task_deps.c.task_id).where(db.task_deps.c.depends_on == task_id)).scalars().all()
    for dependent in dependents:
        if _deps_done(conn, dependent):
            changed += _open(conn, dependent)
    return changed


def release_slot(conn: Connection, task_id: str) -> None:
    conn.execute(update(db.pool_slots).where(db.pool_slots.c.task_id == task_id).values(task_id=None, leased_until=None))


def _lease_until():
    return db.now() + timedelta(seconds=LEASE_SECONDS)


def claim(conn: Connection, worker_id: str, pools: list[str] | None = None) -> dict | None:
    """Take one task. Resumes orphaned upstream jobs first, then starts new work in free slots."""
    pool_filter = "TRUE" if not pools else "t.pool = ANY(:pools)"
    resumed = conn.execute(text(f"""
        SELECT t.id FROM tasks t
        WHERE t.status = 'submitted' AND t.lease_expires_at < now() AND {pool_filter}
        ORDER BY t.priority DESC, t.submitted_at
        LIMIT 1 FOR UPDATE SKIP LOCKED
    """), {"pools": pools or []}).scalar()
    if resumed:
        task = _row(conn, resumed)
        held = conn.execute(select(db.pool_slots.c.slot).where(db.pool_slots.c.task_id == resumed)).first()
        if not held:
            slot = conn.execute(text("""
                SELECT slot FROM pool_slots WHERE pool = :pool AND task_id IS NULL
                ORDER BY slot LIMIT 1 FOR UPDATE SKIP LOCKED
            """), {"pool": task["pool"]}).scalar()
            if slot is not None:
                conn.execute(update(db.pool_slots).where(
                    db.pool_slots.c.pool == task["pool"], db.pool_slots.c.slot == slot,
                ).values(task_id=resumed, leased_until=_lease_until()))
        conn.execute(update(db.tasks).where(db.tasks.c.id == resumed).values(
            lease_owner=worker_id, lease_expires_at=_lease_until(),
        ))
        slot = conn.execute(select(db.pool_slots.c.slot).where(db.pool_slots.c.task_id == resumed)).scalar()
        return {**_row(conn, resumed), "resumed": True, "slot": slot or 0}

    names = conn.execute(text("""
        SELECT name, rate_per_minute FROM pools
        WHERE NOT paused AND name <> 'gate' AND (:all OR name = ANY(:pools))
    """), {"all": not pools, "pools": pools or []}).all()
    names = list(names)
    random.shuffle(names)
    for pool, rate in names:
        slot = conn.execute(text("""
            SELECT slot FROM pool_slots WHERE pool = :pool AND task_id IS NULL
            ORDER BY slot LIMIT 1 FOR UPDATE SKIP LOCKED
        """), {"pool": pool}).scalar()
        if slot is None:
            continue
        if rate:
            started = conn.execute(text("""
                SELECT count(*) FROM tasks WHERE pool = :pool AND started_at > now() - interval '1 minute'
            """), {"pool": pool}).scalar_one()
            if started >= rate:
                continue
        task_id = conn.execute(text("""
            SELECT t.id FROM tasks t
            WHERE t.pool = :pool AND t.status = 'ready' AND (t.ready_at IS NULL OR t.ready_at <= now())
              AND NOT EXISTS (
                SELECT 1 FROM runs r WHERE r.id = t.run_id AND r.status IN ('paused', 'canceled', 'failed')
              )
            ORDER BY (t.priority + floor(extract(epoch FROM now() - coalesce(t.ready_at, t.created_at)) / 1800)) DESC,
                     t.sort_key, t.created_at
            LIMIT 1 FOR UPDATE SKIP LOCKED
        """), {"pool": pool}).scalar()
        if not task_id:
            continue
        conn.execute(update(db.pool_slots).where(db.pool_slots.c.pool == pool, db.pool_slots.c.slot == slot)
                     .values(task_id=task_id, leased_until=_lease_until()))
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
            status="leased", lease_owner=worker_id, lease_expires_at=_lease_until(),
            attempts=db.tasks.c.attempts + 1, started_at=func.coalesce(db.tasks.c.started_at, func.now()),
        ))
        return {**_row(conn, task_id), "resumed": False, "slot": slot}
    return None


def heartbeat(conn: Connection, worker_id: str, task_ids: list[str]) -> None:
    if not task_ids:
        return
    conn.execute(update(db.tasks).where(
        db.tasks.c.id.in_(task_ids), db.tasks.c.lease_owner == worker_id, db.tasks.c.status.in_(ACTIVE),
    ).values(lease_expires_at=_lease_until()))
    conn.execute(update(db.pool_slots).where(db.pool_slots.c.task_id.in_(task_ids)).values(leased_until=_lease_until()))


def set_status(conn: Connection, task_id: str, status: str, **values) -> None:
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(status=status, **values))
    db.notify(conn, "cvgen_events", task_id)


def set_progress(conn: Connection, task_id: str, fraction: float | None, message: str = "") -> None:
    values = {"output": func.coalesce(db.tasks.c.output, text("'{}'::jsonb")).op("||")(
        func.jsonb_build_object("progress_message", message))}
    if fraction is not None:
        values["progress"] = max(0.0, min(1.0, float(fraction)))
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(**values))


def complete(conn: Connection, task_id: str, output: dict) -> list[str]:
    task = _row(conn, task_id)
    merged = {**(task["output"] or {}), **output}
    merged.pop("progress_message", None)
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
        status="succeeded", output=merged, finished_at=db.now(), lease_owner=None, lease_expires_at=None,
        progress=1.0, error=None, attention="",
    ))
    release_slot(conn, task_id)
    db.notify(conn, "cvgen_events", task["run_id"] or task["work_id"] or "")
    return unblock_dependents(conn, task_id)


def fail(conn: Connection, task_id: str, error: dict, *, retry: bool) -> str:
    """Returns 'retry' when the task goes back to the queue, 'failed' otherwise."""
    task = _row(conn, task_id)
    release_slot(conn, task_id)
    if retry and task["attempts"] < task["max_attempts"]:
        delay = task["backoff_seconds"] * max(1, task["attempts"])
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
            status="ready", ready_at=db.now() + timedelta(seconds=delay), provider_ref=None,
            lease_owner=None, lease_expires_at=None, error=error,
        ))
        db.notify(conn, "cvgen_tasks", task["pool"])
        return "retry"
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
        status="failed", error=error, finished_at=db.now(), lease_owner=None, lease_expires_at=None,
    ))
    db.notify(conn, "cvgen_events", task["run_id"] or task["work_id"] or "")
    return "failed"


def park(conn: Connection, task_id: str, reason: str, error: dict | None = None, keep_slot: bool = False) -> None:
    """A person must decide. The provider reference is kept so the job can be re-queried later."""
    if not keep_slot:
        release_slot(conn, task_id)
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
        status="needs_attention", attention=reason, error=error or {"message": reason},
        lease_owner=None, lease_expires_at=None,
    ))
    db.notify(conn, "cvgen_events", task_id)


def mark_canceled(conn: Connection, task_id: str, output: dict | None = None) -> None:
    task = _row(conn, task_id)
    values = {"status": "canceled", "finished_at": db.now(), "lease_owner": None, "lease_expires_at": None}
    if output:
        values["output"] = {**(task["output"] or {}), **output}
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(**values))
    release_slot(conn, task_id)
    db.notify(conn, "cvgen_events", task["run_id"] or task["work_id"] or "")


def request_cancel(conn: Connection, principal, task_id: str) -> dict:
    task = _row(conn, task_id, lock=True)
    if not task:
        raise LookupError("没有这个任务")
    if task["status"] in TERMINAL:
        return task
    if task["status"] in ACTIVE:
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(cancel_requested=True))
    else:
        mark_canceled(conn, task_id)
    events.record(conn, principal, "task.cancel", workspace_id=task["workspace_id"], work_id=task["work_id"],
                  run_id=task["run_id"], target_kind=task["kind"], target_id=task_id)
    return _row(conn, task_id)


def cancel_requested(conn: Connection, task_id: str) -> bool:
    return bool(conn.execute(select(db.tasks.c.cancel_requested).where(db.tasks.c.id == task_id)).scalar())


def supersede(conn: Connection, principal, task_id: str, *, input_patch: dict | None = None) -> dict:
    """Rerun: a fresh copy takes over the old task's place in the dependency graph. The old row stays."""
    old = _row(conn, task_id)
    new = create(
        conn, principal, workspace_id=old["workspace_id"], kind=old["kind"], pool=old["pool"],
        input={**(old["input"] or {}), **(input_patch or {})}, run_id=old["run_id"], work_id=old["work_id"],
        node_id=old["node_id"], item_key=old["item_key"], item_index=old["item_index"],
        provider_instance=old["provider_instance"], priority=old["priority"], sort_key=old["sort_key"],
        max_attempts=old["max_attempts"], backoff_seconds=old["backoff_seconds"],
        timeout_seconds=old["timeout_seconds"], retry_safe=old["retry_safe"], depends_on=deps_of(conn, task_id),
    )
    conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(superseded_by=new["id"]))
    conn.execute(update(db.task_deps).where(db.task_deps.c.depends_on == task_id).values(depends_on=new["id"]))
    for dependent in conn.execute(select(db.task_deps.c.task_id).where(db.task_deps.c.depends_on == new["id"])).scalars():
        conn.execute(update(db.tasks).where(db.tasks.c.id == dependent, db.tasks.c.status.in_(("ready", "waiting")))
                     .values(status="blocked", ready_at=None))
    return new


def janitor(conn: Connection) -> dict:
    """Recover from crashed workers and keep slots consistent. Safe to run from every worker."""
    if not conn.execute(text("SELECT pg_try_advisory_xact_lock(4242)")).scalar():
        return {"skipped": True}
    requeued = conn.execute(text("""
        UPDATE tasks SET status = 'ready', ready_at = now(), lease_owner = NULL, lease_expires_at = NULL
        WHERE status IN ('leased', 'running') AND lease_expires_at < now()
        RETURNING id, pool
    """)).all()
    unsafe = conn.execute(text("""
        UPDATE tasks SET status = 'needs_attention', lease_owner = NULL, lease_expires_at = NULL,
               attention = '提交途中 worker 中断，不知道上游是否已受理。核对后选择重新查询、标记失败或强制重提。'
        WHERE status = 'submitting' AND lease_expires_at < now() AND NOT retry_safe
        RETURNING id
    """)).all()
    safe = conn.execute(text("""
        UPDATE tasks SET status = 'ready', ready_at = now(), lease_owner = NULL, lease_expires_at = NULL
        WHERE status = 'submitting' AND lease_expires_at < now() AND retry_safe
        RETURNING id, pool
    """)).all()
    for row in [*requeued, *safe]:
        release_slot(conn, row.id)
        db.notify(conn, "cvgen_tasks", row.pool)
    for row in unsafe:
        release_slot(conn, row.id)
    freed = conn.execute(text("""
        UPDATE pool_slots s SET task_id = NULL, leased_until = NULL
        WHERE s.task_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM tasks t WHERE t.id = s.task_id AND t.status IN ('leased', 'running', 'submitting', 'submitted')
        )
        RETURNING pool
    """)).all()
    conn.execute(text("""
        DELETE FROM pool_slots s USING pools p
        WHERE s.pool = p.name AND s.slot >= p.concurrency AND s.task_id IS NULL
    """))
    for row in freed:
        db.notify(conn, "cvgen_tasks", row.pool)
    return {"requeued": len(requeued) + len(safe), "parked": len(unsafe), "freed_slots": len(freed)}


def resolve_attention(conn: Connection, principal, task_id: str, action: str, artifact_id: str | None = None) -> dict:
    """needs_attention → requery (resume polling), fail, resubmit (admin), or attach a result by hand."""
    task = _row(conn, task_id, lock=True)
    if not task or task["status"] != "needs_attention":
        raise ValueError("这个任务不在待处理状态")
    if action == "requery":
        if not task["provider_ref"]:
            raise ValueError("没有上游任务号，不能重新查询")
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
            status="submitted", lease_expires_at=db.now() - timedelta(seconds=1), attention="",
        ))
        db.notify(conn, "cvgen_tasks", task["pool"])
    elif action == "fail":
        fail(conn, task_id, {"message": "人工标记失败", **(task["error"] or {})}, retry=False)
    elif action == "resubmit":
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
            status="ready", ready_at=db.now(), provider_ref=None, attention="", attempts=0,
            max_attempts=func.greatest(db.tasks.c.max_attempts, 1),
        ))
        db.notify(conn, "cvgen_tasks", task["pool"])
    elif action == "approve":
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
            status="ready", ready_at=db.now(), attention="", input=func.jsonb_set(
                db.tasks.c.input, text("'{approved_by}'"), func.to_jsonb(principal.name)),
        ))
        db.notify(conn, "cvgen_tasks", task["pool"])
    elif action == "attach":
        if not artifact_id:
            raise ValueError("挂接产物需要文件 id")
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
            output={**(task["output"] or {}), "manual_artifact_id": artifact_id}, attention="",
            status="ready", ready_at=db.now(),
        ))
        db.notify(conn, "cvgen_tasks", task["pool"])
    else:
        raise ValueError("动作只能是 approve、requery、fail、resubmit、attach")
    events.record(conn, principal, f"task.{action}", workspace_id=task["workspace_id"], work_id=task["work_id"],
                  run_id=task["run_id"], target_kind=task["kind"], target_id=task_id)
    return _row(conn, task_id)


def list_tasks(conn: Connection, *, workspace_id: str | None = None, run_id: str | None = None,
               work_id: str | None = None, statuses: list[str] | None = None, pool: str | None = None,
               limit: int = 100, include_superseded: bool = False) -> list[dict]:
    query = select(db.tasks)
    conditions = []
    if workspace_id:
        conditions.append(db.tasks.c.workspace_id == workspace_id)
    if run_id:
        conditions.append(db.tasks.c.run_id == run_id)
    if work_id:
        conditions.append(db.tasks.c.work_id == work_id)
    if statuses:
        conditions.append(db.tasks.c.status.in_(statuses))
    if pool:
        conditions.append(db.tasks.c.pool == pool)
    if not include_superseded:
        conditions.append(db.tasks.c.superseded_by.is_(None))
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(db.tasks.c.created_at.desc()).limit(limit)
    return [dict(row) for row in conn.execute(query).mappings()]


def queue_position(conn: Connection, task: dict) -> int | None:
    if task["status"] != "ready":
        return None
    return conn.execute(text("""
        SELECT count(*) FROM tasks t
        WHERE t.pool = :pool AND t.status = 'ready' AND t.id <> :id AND (
            t.priority > :priority OR (t.priority = :priority AND (t.sort_key, t.created_at) < (:sort_key, :created_at))
        )
    """), {"pool": task["pool"], "id": task["id"], "priority": task["priority"], "sort_key": task["sort_key"],
           "created_at": task["created_at"]}).scalar_one() + 1
