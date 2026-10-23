"""Runs: one published workflow version + inputs. advance() turns ready nodes into queued tasks.

A node is expanded once every node it depends on has tasks, and (for for_each nodes) once its item
list is known. Two nodes over the same list depend item by item, so shot 2's video can start while
shot 3's keyframe is still being drawn. A gate is one task that depends on every task before it.
"""

from __future__ import annotations

import time
from decimal import Decimal

from jsonschema import Draft202012Validator
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.engine import Connection

from .. import artifacts, assets, db, events, graph
from ..engine import tasks as task_q
from ..providers.instances import resolve as resolve_provider
from .spec import analyze, same_items
from .template import EntityRef, Scope

RUN_TERMINAL = ("succeeded", "failed", "canceled")
GEN_KINDS = {"llm", "image", "video", "tts", "music"}
LOCAL_POOL = {"check": "ffmpeg", "edit": "ffmpeg", "gate": task_q.GATE_POOL}


class RunError(ValueError):
    pass


def get_version(conn: Connection, workflow_id: str, version: int | None = None, published_only: bool = True) -> dict:
    query = select(db.workflow_versions, db.workflows.c.name, db.workflows.c.workspace_id).join(
        db.workflows, db.workflows.c.id == db.workflow_versions.c.workflow_id,
    ).where(db.workflow_versions.c.workflow_id == workflow_id)
    if version:
        query = query.where(db.workflow_versions.c.version == version)
    elif published_only:
        query = query.where(db.workflow_versions.c.status == "published")
    row = conn.execute(query.order_by(db.workflow_versions.c.version.desc()).limit(1)).mappings().first()
    if not row:
        raise RunError("没有这个工作流版本" if version else "这个工作流还没有已发布的版本")
    if published_only and row["status"] != "published":
        raise RunError(f"版本 {row['version']} 还没有发布")
    return dict(row)


def get_run(conn: Connection, run_id: str, lock: bool = False) -> dict | None:
    query = select(db.runs).where(db.runs.c.id == run_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).mappings().first()
    return dict(row) if row else None


def input_errors(spec: dict, inputs: dict) -> list[str]:
    validator = Draft202012Validator(spec.get("inputs") or {"type": "object"})
    problems = []
    for error in validator.iter_errors(inputs):
        where = ".".join(str(part) for part in error.absolute_path) or "inputs"
        problems.append(f"{where}：{error.message}")
    return problems


def create_run(
    conn: Connection,
    principal,
    *,
    workflow_id: str,
    version: int | None,
    inputs: dict,
    mode: str = "production",
    priority: int = 0,
    batch_id: str | None = None,
    callback_url: str = "",
    idempotency_key: str | None = None,
    auto_gates: bool = False,
) -> dict:
    if idempotency_key:
        existing = conn.execute(select(db.runs).where(
            db.runs.c.created_by_kind == principal.kind, db.runs.c.created_by_id == principal.id,
            db.runs.c.idempotency_key == idempotency_key,
        )).mappings().first()
        if existing:
            return {**dict(existing), "idempotent_replay": True}
    workflow_version = get_version(conn, workflow_id, version, published_only=mode == "production")
    principal.check_workspace(workflow_version["workspace_id"])
    spec = workflow_version["spec"]
    problems = input_errors(spec, inputs)
    if problems:
        raise RunError("输入不符合工作流要求：" + "；".join(problems))
    run_id = db.new_id("run")
    workspace_id = workflow_version["workspace_id"]
    work = graph.create_work(conn, principal, workspace_id, f"{workflow_version['name']} · {run_id[-6:]}",
                             kind="运行", origin="run", run_id=run_id)
    uploads = _materialize_uploads(conn, principal, spec, inputs, work["id"], workspace_id)
    estimate = Decimal("0")
    budget = Decimal(str((spec.get("budget") or {}).get("max_yuan", 0)))
    if workflow_version.get("fixtures"):
        from .dryrun import compile_run

        try:
            estimate = Decimal(str(compile_run(conn, workspace_id, spec, inputs, workflow_version["fixtures"])["estimate_yuan"]))
        except Exception:
            estimate = Decimal("0")
    if budget and estimate > budget:
        raise RunError(f"估算花费 {estimate} 元超过预算 {budget} 元")
    conn.execute(insert(db.runs).values(
        id=run_id, workspace_id=workspace_id, workflow_id=workflow_id, version=workflow_version["version"],
        batch_id=batch_id, mode=mode, inputs=inputs, status="running", priority=priority, work_id=work["id"],
        context={"uploads": uploads}, auto_gates=auto_gates, cost_estimate=estimate,
        created_by_kind=principal.kind, created_by_id=principal.id, idempotency_key=idempotency_key,
        callback_url=callback_url or "", seq=int(time.time() * 1000), started_at=db.now(),
    ))
    events.record(conn, principal, "run.create", workspace_id=workspace_id, work_id=work["id"], run_id=run_id,
                  target_kind="run", target_id=run_id,
                  payload={"workflow": workflow_version["name"], "version": workflow_version["version"], "mode": mode})
    _webhook(conn, run_id, "run.started")
    advance(conn, run_id, principal)
    return get_run(conn, run_id)


def _materialize_uploads(conn, principal, spec: dict, inputs: dict, work_id: str, workspace_id: str) -> dict:
    uploads: dict[str, list[str]] = {}
    for field_name, field in (spec.get("inputs") or {}).get("properties", {}).items():
        item_spec = field.get("items") if field.get("type") == "array" else field
        if not item_spec or item_spec.get("format") != "asset-upload" or field_name not in inputs:
            continue
        values = inputs[field_name] if isinstance(inputs[field_name], list) else [inputs[field_name]]
        ids = []
        for artifact_id in values:
            row = artifacts.get(conn, artifact_id)
            if not row or row["workspace_id"] != workspace_id:
                raise RunError(f"{field_name}：找不到上传的文件 {artifact_id}")
            entity = graph.add_entity(conn, principal, work_id, "Reference", {
                "title": row["label"] or field.get("title") or field_name,
                "role": item_spec.get("x-role") or "身份",
                "take": "只采用图中的主体外形和标识",
                "ignore": "不采用背景和光线",
            }, artifact_id=artifact_id)
            ids.append(entity["id"])
        uploads[field_name] = ids
    return uploads


def current_tasks(conn: Connection, run_id: str) -> list[dict]:
    rows = conn.execute(select(db.tasks).where(db.tasks.c.run_id == run_id, db.tasks.c.superseded_by.is_(None))
                        .order_by(db.tasks.c.node_id, db.tasks.c.item_index)).mappings()
    return [dict(row) for row in rows]


def scope_for(conn: Connection, run: dict, spec: dict, item=None, item_index: int = 0, by_node: dict | None = None) -> Scope:
    by_node = by_node if by_node is not None else _group(current_tasks(conn, run["id"]))
    analysis = analyze(spec)

    def node_output(node_id: str):
        node_tasks = by_node.get(node_id, [])
        if analysis.nodes.get(node_id, {}).get("for_each"):
            return [task["output"] for task in node_tasks]
        return node_tasks[0]["output"] if node_tasks else {}

    return Scope(
        run=run, spec=spec, graph=graph.DbGraph(conn, run["workspace_id"]),
        asset_lookup=lambda ref: assets.resolve(conn, run["workspace_id"], ref),
        node_output=node_output, item=item, item_index=item_index,
    )


def _group(task_rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for task in task_rows:
        grouped.setdefault(task["node_id"], []).append(task)
    for items in grouped.values():
        items.sort(key=lambda task: task["item_index"])
    return grouped


def _items(conn, run: dict, spec: dict, analysis, node_id: str, by_node: dict) -> list[tuple[str, int, object]] | None:
    root = analysis.roots.get(node_id)
    if root is None:
        return None
    if root[0] == "inputs":
        uploads = (run.get("context") or {}).get("uploads") or {}
        values = uploads.get(root[1]) or (run.get("inputs") or {}).get(root[1])
        values = values if isinstance(values, list) else ([values] if values is not None else [])
        if root[1] in uploads:
            values = [EntityRef(value) for value in values]
    else:
        source_tasks = by_node.get(root[1], [])
        if not source_tasks or any(task["status"] != "succeeded" for task in source_tasks):
            return None
        output = source_tasks[0]["output"] or {}
        if root[2] in (output.get("entities") or {}):
            values = [EntityRef(entity_id) for entity_id in output["entities"][root[2]]]
        else:
            raw = (output.get("json") or {}).get(root[2])
            values = raw if isinstance(raw, list) else ([raw] if raw is not None else [])
    return [(f"{index:03d}", index, value) for index, value in enumerate(values)]


def _sort_key(run: dict, policy: dict, item_index: int, node_order: int) -> str:
    if policy.get("gpu_order") == "round_robin":
        return f"{item_index:05d}:{run['seq']:015d}:{node_order:03d}"
    return f"{run['seq']:015d}:{item_index:05d}:{node_order:03d}"


def _batch_ready(conn: Connection, run: dict) -> bool:
    if not run.get("batch_id"):
        return True
    pending = conn.execute(text("""
        SELECT count(*) FROM tasks t JOIN runs r ON r.id = t.run_id
        WHERE r.batch_id = :batch AND t.kind = 'image' AND t.superseded_by IS NULL
          AND t.status NOT IN ('succeeded', 'canceled')
    """), {"batch": run["batch_id"]}).scalar_one()
    return pending == 0


def advance(conn: Connection, run_id: str, principal=None) -> dict:
    """Expand every node that can be expanded now, then recompute the run's status. Idempotent."""
    from ..auth import SYSTEM

    principal = principal or SYSTEM
    run = get_run(conn, run_id, lock=True)
    if not run or run["status"] in RUN_TERMINAL:
        return run
    version = get_version(conn, run["workflow_id"], run["version"], published_only=False)
    spec = version["spec"]
    analysis = analyze(spec)
    by_node = _group(current_tasks(conn, run_id))
    order_index = {node_id: index for index, node_id in enumerate(analysis.order)}
    policy = spec.get("policy") or {}
    progressed = True
    while progressed:
        progressed = False
        for node_id in analysis.order:
            if node_id in by_node:
                continue
            node = analysis.nodes[node_id]
            if run["mode"] == "dryrun-llm" and node["kind"] != "llm":
                continue
            if any(dep not in by_node for dep in analysis.deps[node_id]):
                continue
            if node["kind"] == "video" and policy.get("batch_barrier") and not _batch_ready(conn, run):
                continue
            items = _items(conn, run, spec, analysis, node_id, by_node) if node.get("for_each") else [("", 0, None)]
            if items is None:
                continue
            by_node[node_id] = _expand(conn, principal, run, spec, analysis, node, items, by_node, order_index, policy)
            progressed = True
    return _refresh_status(conn, run, spec, analysis, principal)


def _expand(conn, principal, run, spec, analysis, node, items, by_node, order_index, policy) -> list[dict]:
    kind = node["kind"]
    provider_ref = node.get("provider")
    pool = LOCAL_POOL.get(kind)
    retry_safe, max_attempts, timeout = True, 1, int(node.get("timeout_seconds") or 1800)
    if kind in GEN_KINDS:
        instances = resolve_provider(conn, provider_ref, kind)
        if not instances:
            raise RunError(f"{node['id']}：没有可用的供应商 {provider_ref}")
        pool = instances[0].pool
        retry_safe = all(instance.retry_safe for instance in instances)
        default_attempts = instances[0].max_attempts if retry_safe else 1
        max_attempts = int((node.get("retry") or {}).get("max_attempts", default_attempts)) if retry_safe else 1
        timeout = int(node.get("timeout_seconds") or instances[0].timeout_seconds)
    elif kind in {"check", "edit"}:
        max_attempts = int((node.get("retry") or {}).get("max_attempts", 2))
    backoff = int((node.get("retry") or {}).get("backoff_seconds", 30))
    created = []
    for item_key, item_index, value in items:
        deps: list[str] = []
        for dep in analysis.deps[node["id"]]:
            dep_tasks = by_node.get(dep, [])
            if item_key and same_items(analysis, node["id"], dep):
                matched = [task["id"] for task in dep_tasks if task["item_key"] == item_key]
                deps += matched or [task["id"] for task in dep_tasks]
            else:
                deps += [task["id"] for task in dep_tasks]
        if kind == "video" and node.get("continuity") == "previous_last_frame" and created:
            deps.append(created[-1]["id"])
        item_value = value.id if isinstance(value, EntityRef) else value
        task_input = {"node": node, "item": item_value, "item_is_entity": isinstance(value, EntityRef)}
        if kind == "gate":
            task_input["auto_approve"] = bool(node.get("auto_approve") or run["auto_gates"])
        if kind == "video" and node.get("continuity") == "previous_last_frame" and created:
            task_input["prev_task"] = created[-1]["id"]
        created.append(task_q.create(
            conn, principal, workspace_id=run["workspace_id"], kind=kind, pool=pool, input=task_input,
            run_id=run["id"], work_id=run["work_id"], node_id=node["id"], item_key=item_key, item_index=item_index,
            provider_instance=provider_ref, priority=int(run["priority"]) + int(node.get("priority") or 0),
            sort_key=_sort_key(run, policy, item_index, order_index[node["id"]]), max_attempts=max_attempts,
            backoff_seconds=backoff, timeout_seconds=timeout, retry_safe=retry_safe, depends_on=deps,
        ))
    if not items:
        created.append(task_q.create(
            conn, principal, workspace_id=run["workspace_id"], kind="gate", pool=task_q.GATE_POOL,
            input={"node": {"id": node["id"], "kind": "gate"}, "empty": True, "auto_approve": True},
            run_id=run["id"], work_id=run["work_id"], node_id=node["id"], item_key="", depends_on=[],
        ))
    return created


def _refresh_status(conn, run: dict, spec: dict, analysis, principal) -> dict:
    task_rows = current_tasks(conn, run["id"])
    failed = [task for task in task_rows if task["status"] == "failed"]
    canceled = [task for task in task_rows if task["status"] == "canceled"]
    if failed or canceled:
        culprit = (failed or canceled)[0]
        message = (culprit["error"] or {}).get("message") or ("任务被取消" if not failed else "任务失败")
        return _finish(conn, run, "failed", principal, error={"node": culprit["node_id"], "task": culprit["id"],
                                                               "item": culprit["item_key"], "message": message})
    expanded = {task["node_id"] for task in task_rows}
    wanted = [node_id for node_id in analysis.order
              if run["mode"] != "dryrun-llm" or analysis.nodes[node_id]["kind"] == "llm"]
    if all(node_id in expanded for node_id in wanted) and all(task["status"] == "succeeded" for task in task_rows):
        return _finish(conn, run, "succeeded", principal, outputs=_outputs(conn, run, spec, task_rows))
    if run["status"] == "paused":
        return get_run(conn, run["id"])
    waiting = any(task["status"] in {"waiting", "needs_attention"} for task in task_rows)
    status = "waiting" if waiting else "running"
    if status != run["status"]:
        conn.execute(update(db.runs).where(db.runs.c.id == run["id"]).values(status=status))
        if status == "waiting" and any(task["status"] == "waiting" for task in task_rows):
            _webhook(conn, run["id"], "run.gate_pending")
        db.notify(conn, "cvgen_events", run["id"])
    return get_run(conn, run["id"])


def _finish(conn, run: dict, status: str, principal, outputs: dict | None = None, error: dict | None = None) -> dict:
    values = {"status": status, "finished_at": db.now()}
    if outputs is not None:
        values["outputs"] = outputs
    if error is not None:
        values["error"] = error
    if run["mode"] == "dryrun-llm" and status == "succeeded":
        from .dryrun import compile_from_run

        values["outputs"] = {"compiled": compile_from_run(conn, run)}
    conn.execute(update(db.runs).where(db.runs.c.id == run["id"]).values(**values))
    if status != "succeeded":
        for task in current_tasks(conn, run["id"]):
            if task["status"] in ("blocked", "ready", "waiting", "needs_attention"):
                task_q.mark_canceled(conn, task["id"])
            elif task["status"] in task_q.ACTIVE:
                conn.execute(update(db.tasks).where(db.tasks.c.id == task["id"]).values(cancel_requested=True))
    events.record(conn, principal, f"run.{status}", workspace_id=run["workspace_id"], work_id=run["work_id"],
                  run_id=run["id"], target_kind="run", target_id=run["id"], payload=error or {})
    _webhook(conn, run["id"], f"run.{status}")
    return get_run(conn, run["id"])


def _outputs(conn, run: dict, spec: dict, task_rows: list[dict]) -> dict:
    by_node = _group(task_rows)
    result = {}
    for name, path in (spec.get("outputs") or {}).items():
        node_id, _, field = path.partition(".")
        items = []
        for task in by_node.get(node_id, []):
            output = task["output"] or {}
            picked = output.get(field) if field and isinstance(output.get(field), dict) else output
            items.append({
                "item": task["item_key"],
                "artifact_id": picked.get("artifact_id") or output.get("artifact_id"),
                "entity_id": picked.get("clip_id") or picked.get("entity_id") or output.get("attached"),
            })
        result[name] = items
    flags = [{"node": task["node_id"], "item": task["item_key"], "problems": task["output"].get("problems")}
             for task in task_rows if task["kind"] == "check" and not (task["output"] or {}).get("passed", True)]
    if flags:
        result["_flags"] = flags
    return result


def _webhook(conn: Connection, run_id: str, event: str) -> None:
    run = get_run(conn, run_id)
    if not run or not run["callback_url"]:
        return
    payload = {"event": event, "run_id": run_id, "status": run["status"], "workflow_id": run["workflow_id"],
               "version": run["version"], "batch_id": run["batch_id"]}
    signer = f"apikey:{run['created_by_id']}" if run["created_by_kind"] == "apikey" else "global"
    conn.execute(insert(db.webhook_deliveries).values(run_id=run_id, url=run["callback_url"], event=event,
                                                      payload=payload, signer=signer))


def task_finished(conn: Connection, task: dict, principal=None) -> None:
    """Called in the same transaction that finished a task."""
    if task.get("run_id"):
        advance(conn, task["run_id"], principal)


def handle_check(conn: Connection, principal, task: dict, passed: bool) -> dict:
    """Decide what a failed check means for the run. Returns extra output for the check task."""
    node = task["input"]["node"]
    if passed or not task.get("run_id"):
        return {}
    policy = node.get("on_fail", "flag")
    if policy == "flag":
        return {"flagged": True}
    upstream_node = node["for_each"].split(".", 1)[0]
    reruns = int((task["input"] or {}).get("reruns", 0))
    if policy == "rerun_upstream" and reruns < int(node.get("max_reruns", 1)):
        upstream = conn.execute(select(db.tasks).where(
            db.tasks.c.run_id == task["run_id"], db.tasks.c.node_id == upstream_node,
            db.tasks.c.item_key == task["item_key"], db.tasks.c.superseded_by.is_(None),
        )).mappings().first()
        if upstream:
            fresh_upstream = task_q.supersede(conn, principal, upstream["id"])
            fresh_check = task_q.supersede(conn, principal, task["id"], input_patch={"reruns": reruns + 1})
            events.record(conn, principal, "check.rerun", workspace_id=task["workspace_id"], run_id=task["run_id"],
                          target_kind="task", target_id=fresh_upstream["id"], payload={"item": task["item_key"]})
            return {"rerun": {"upstream": fresh_upstream["id"], "check": fresh_check["id"]}}
    raise RunError(f"{node['id']} 检查不通过：" + "；".join(task.get("problems") or []))


def decide_gate(conn: Connection, principal, task_id: str, decision: str, *, note: str = "",
                selections: dict | None = None, redo: list[str] | None = None) -> dict:
    task = task_q.get(conn, task_id)
    if not task or task["kind"] != "gate":
        raise RunError("没有这个闸门")
    if task["status"] != "waiting":
        raise RunError("这个闸门现在不需要审批")
    node = task["input"]["node"]
    principal.require(f"gates:decide:{node.get('approvers', 'reviewer')}")
    run = get_run(conn, task["run_id"], lock=True)
    task = task_q.get(conn, task_id)
    if task["status"] != "waiting":
        raise RunError("这个闸门现在不需要审批")
    if decision == "approve":
        applied = _apply_selections(conn, principal, run, node, selections or {})
        task_q.complete(conn, task_id, {"decision": "approved", "by": principal.name, "note": note, "selections": applied})
    elif decision == "reject" and redo:
        if not node.get("allow_redo", True):
            raise RunError("这个闸门不允许只重跑部分条目")
        reran = []
        for shown in node.get("show", []):
            for item_key in redo:
                old = conn.execute(select(db.tasks).where(
                    db.tasks.c.run_id == run["id"], db.tasks.c.node_id == shown, db.tasks.c.item_key == item_key,
                    db.tasks.c.superseded_by.is_(None), db.tasks.c.kind != "llm",
                )).mappings().first()
                if old:
                    reran.append(task_q.supersede(conn, principal, old["id"])["id"])
        if not reran:
            raise RunError("没有找到要重跑的条目")
        conn.execute(update(db.tasks).where(db.tasks.c.id == task_id).values(
            status="blocked", output={"last_decision": "redo", "by": principal.name, "note": note, "redo": redo},
        ))
    elif decision == "reject":
        task_q.fail(conn, task_id, {"message": f"闸门被驳回：{note or '未写理由'}", "by": principal.name}, retry=False)
    else:
        raise RunError("decision 只能是 approve 或 reject")
    events.record(conn, principal, f"gate.{decision}", workspace_id=task["workspace_id"], work_id=task["work_id"],
                  run_id=task["run_id"], target_kind="gate", target_id=task_id,
                  payload={"note": note, "redo": redo or [], "selections": selections or {}})
    advance(conn, run["id"], principal)
    return task_q.get(conn, task_id)


def _apply_selections(conn, principal, run: dict, gate: dict, selections: dict) -> dict:
    """Image nodes with select=gate attach the chosen candidate (default: the first) to their item."""
    applied = {}
    version = get_version(conn, run["workflow_id"], run["version"], published_only=False)
    analysis = analyze(version["spec"])
    for shown in gate.get("show", []):
        node = analysis.nodes.get(shown, {})
        if node.get("kind") != "image" or node.get("select") != "gate":
            continue
        for task in current_tasks(conn, run["id"]):
            if task["node_id"] != shown:
                continue
            output = task["output"] or {}
            candidates = [item["entity_id"] for item in output.get("candidates", [])]
            chosen = selections.get(f"{shown}:{task['item_key']}") or selections.get(task["item_key"])
            chosen = chosen if chosen in candidates else (candidates[0] if candidates else None)
            if not chosen or not output.get("attach_to"):
                continue
            graph.add_link(conn, principal, run["work_id"], "references", output["attach_to"], chosen, "闸门选定")
            conn.execute(update(db.tasks).where(db.tasks.c.id == task["id"]).values(
                output={**output, "attached": chosen},
            ))
            applied[f"{shown}:{task['item_key']}"] = chosen
    return applied


def rerun_item(conn: Connection, principal, run_id: str, node_id: str, item_key: str) -> list[str]:
    run = get_run(conn, run_id, lock=True)
    if not run:
        raise RunError("没有这个运行")
    old = conn.execute(select(db.tasks).where(
        db.tasks.c.run_id == run_id, db.tasks.c.node_id == node_id, db.tasks.c.item_key == item_key,
        db.tasks.c.superseded_by.is_(None),
    )).mappings().first()
    if not old:
        raise RunError("没有这一条")
    if old["status"] not in task_q.TERMINAL and old["status"] != "needs_attention":
        raise RunError("这一条还在执行，不能重跑")
    created = [task_q.supersede(conn, principal, old["id"])["id"]]
    frontier = list(created)
    while frontier:
        current = frontier.pop()
        dependents = conn.execute(select(db.task_deps.c.task_id).where(db.task_deps.c.depends_on == current)).scalars().all()
        for dependent in dependents:
            row = task_q.get(conn, dependent)
            if row and row["superseded_by"] is None and row["status"] in (*task_q.TERMINAL, "needs_attention"):
                fresh = task_q.supersede(conn, principal, dependent)["id"]
                created.append(fresh)
                frontier.append(fresh)
    conn.execute(update(db.runs).where(db.runs.c.id == run_id).values(status="running", finished_at=None, error=None))
    events.record(conn, principal, "run.rerun_item", workspace_id=run["workspace_id"], work_id=run["work_id"],
                  run_id=run_id, target_kind="task", target_id=old["id"], payload={"node": node_id, "item": item_key})
    advance(conn, run_id, principal)
    return created


def cancel_run(conn: Connection, principal, run_id: str) -> dict:
    run = get_run(conn, run_id, lock=True)
    if not run:
        raise RunError("没有这个运行")
    if run["status"] in RUN_TERMINAL:
        return run
    return _finish(conn, run, "canceled", principal, error={"message": f"被 {principal.name} 取消"})


def set_paused(conn: Connection, principal, run_id: str, paused: bool) -> dict:
    run = get_run(conn, run_id, lock=True)
    if not run or run["status"] in RUN_TERMINAL:
        raise RunError("这个运行已经结束")
    conn.execute(update(db.runs).where(db.runs.c.id == run_id).values(status="paused" if paused else "running"))
    events.record(conn, principal, "run.pause" if paused else "run.resume", workspace_id=run["workspace_id"],
                  run_id=run_id, target_kind="run", target_id=run_id)
    if not paused:
        for row in conn.execute(select(db.tasks.c.pool).where(db.tasks.c.run_id == run_id, db.tasks.c.status == "ready")):
            db.notify(conn, "cvgen_tasks", row.pool)
        advance(conn, run_id, principal)
    return get_run(conn, run_id)


def record_cost(conn: Connection, task: dict, instance, usage: list, principal=None) -> Decimal:
    """Write ledger rows for one task, add them to the run, and pause the run if it runs over budget."""
    total = Decimal("0")
    for item in usage:
        unit_price = Decimal(str(instance.pricing.get(item.unit, 0)))
        amount = (unit_price * Decimal(str(item.quantity))).quantize(Decimal("0.0001"))
        conn.execute(insert(db.cost_ledger).values(
            workspace_id=task["workspace_id"], task_id=task["id"], run_id=task.get("run_id"), work_id=task.get("work_id"),
            provider_instance=instance.name, unit=item.unit, quantity=item.quantity, unit_price=unit_price,
            amount_yuan=amount, actor_kind=task["created_by_kind"], actor_id=task["created_by_id"],
        ))
        total += amount
    if task.get("run_id") and total:
        conn.execute(update(db.runs).where(db.runs.c.id == task["run_id"]).values(
            cost_actual=db.runs.c.cost_actual + total,
        ))
        run = get_run(conn, task["run_id"])
        version = get_version(conn, run["workflow_id"], run["version"], published_only=False)
        budget = Decimal(str((version["spec"].get("budget") or {}).get("max_yuan", 0)))
        if budget and run["cost_actual"] > budget and run["status"] not in RUN_TERMINAL:
            if (version["spec"].get("policy") or {}).get("on_budget_exceeded", "pause") == "fail":
                from ..auth import SYSTEM

                _finish(conn, run, "failed", principal or SYSTEM,
                        error={"message": f"花费 {run['cost_actual']} 元超过预算 {budget} 元"})
            else:
                conn.execute(update(db.runs).where(db.runs.c.id == run["id"]).values(status="paused"))
                _webhook(conn, run["id"], "run.paused")
    return total


def spent_today(conn: Connection, actor_kind: str, actor_id: str) -> Decimal:
    return Decimal(str(conn.execute(select(func.coalesce(func.sum(db.cost_ledger.c.amount_yuan), 0)).where(
        db.cost_ledger.c.actor_kind == actor_kind, db.cost_ledger.c.actor_id == actor_id,
        db.cost_ledger.c.created_at >= func.date_trunc("day", func.now()),
    )).scalar_one()))
