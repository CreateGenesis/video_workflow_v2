"""The LLM node: render prompts, ask for structured output, check it, repair, then write it into the run."""

from __future__ import annotations

import hashlib
import json

from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import db, graph
from ..compose import compose
from ..engine import tasks as task_q
from ..engine.generate import Park
from ..engine.job import Job
from ..providers.base import Outcome, Usage
from .materialize import DbSink, MemoryGraph, MemorySink, materialize

# Prompt problems the model can fix by rewriting the shot. Reference-related warnings are not here:
# keyframes are drawn after this step, so they cannot exist yet.
FIXABLE_WARNINGS = ("定格被写成正面要求", "一个正向段里可能塞了多个主动作", "正向段超过 4 段", "台词在镜头字段里")


def _schema_problems(schema: dict, value) -> list[str]:
    problems = []
    for error in Draft202012Validator(schema).iter_errors(value):
        where = ".".join(str(part) for part in error.absolute_path) or "(根)"
        problems.append(f"{where}：{error.message}")
    return problems


def _check(conn, job: Job, scope, node: dict, value) -> list[str]:
    problems = _schema_problems(scope.schema(node["output_schema"]), value)
    if problems or not node.get("materialize"):
        return problems
    base = graph.DbGraph(conn, job.task["workspace_id"])
    memory = MemoryGraph(base=base, asset_node=base.get)
    created, problems = materialize(node["materialize"], value, MemorySink(memory), scope)
    if problems:
        return problems
    for ids in created.values():
        for entity_id in ids:
            node_view = memory.get(entity_id)
            if node_view["type"] != "Shot":
                continue
            try:
                plan = compose(memory, entity_id, "768p横")
            except ValueError as exc:
                problems.append(f"{node_view['data'].get('title')}：{exc}")
                continue
            problems += [f"{node_view['data'].get('title')}：{warning}" for warning in plan["warnings"]
                         if any(fixable in warning for fixable in FIXABLE_WARNINGS)]
    return problems


def _cache_key(instance, request: dict) -> str:
    payload = json.dumps({"instance": instance.name, "model": instance.model, "request": request},
                         ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_llm(job: Job) -> None:
    from .runner import record_cost, task_finished

    node = job.node
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        instance, adapter = job.adapter(conn)
        scope = job.scope(conn)
        schema = scope.schema(node["output_schema"])
        system = scope.render(node["prompt"].get("system") or "")
        user = scope.render(node["prompt"]["user"])
        task_q.set_status(conn, job.id, "running")
    params = node.get("params") or {}
    request = {"system": system, "messages": [{"role": "user", "content": user}], "schema": schema,
               "schema_name": node["id"], "temperature": params.get("temperature"),
               "max_tokens": params.get("max_tokens"), "seed": params.get("seed")}
    key = _cache_key(instance, request)
    use_cache = node.get("cache", True)
    transcript = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    usage: list[Usage] = []
    value, problems, attempts, model = None, [], 0, instance.model
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        cached = conn.execute(select(db.llm_cache.c.response).where(db.llm_cache.c.key == key)).scalar() if use_cache else None
        if cached:
            value = cached["json"]
            problems = _check(conn, job, job.scope(conn), node, value)
            transcript.append({"role": "assistant", "content": cached.get("raw", ""), "cached": True})
    if value is None or problems:
        limit = int(node.get("repair", 2)) + 1
        for attempts in range(1, limit + 1):
            outcome: Outcome = adapter.run(request, job.context())
            usage += outcome.usage
            value = outcome.data["json"]
            model = outcome.data.get("model") or model
            transcript.append({"role": "assistant", "content": outcome.data.get("raw", "")})
            with db.tx(lock_run=job.task.get("run_id")) as conn:
                problems = _check(conn, job, job.scope(conn), node, value)
            if not problems or attempts == limit:
                break
            feedback = "上面的输出有这些问题，请修正后重新输出完整的 JSON：\n" + "\n".join(f"- {item}" for item in problems)
            request["messages"] = request["messages"] + [
                {"role": "assistant", "content": outcome.data.get("raw", "")},
                {"role": "user", "content": feedback},
            ]
            transcript.append({"role": "user", "content": feedback})
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        cost = record_cost(conn, job.task, instance, usage) if usage else 0
        if problems:
            conn.execute(db.tasks.update().where(db.tasks.c.id == job.id).values(output={
                "json": value, "problems": problems, "transcript": transcript, "attempts": attempts,
            }))
    if problems:
        raise Park(f"修正 {attempts} 次后仍有问题：" + "；".join(problems[:5]))
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        created = {}
        if node.get("materialize"):
            created, issues = materialize(node["materialize"], value, DbSink(conn, job.principal, job.task["work_id"],
                                                                             job.task.get("run_id")), job.scope(conn))
            if issues:
                raise Park("写入作品时出错：" + "；".join(issues[:5]))
        if use_cache and not cached:
            conn.execute(pg_insert(db.llm_cache).values(
                key=key, response={"json": value, "raw": transcript[-1]["content"]},
            ).on_conflict_do_nothing())
        task_q.complete(conn, job.id, {
            "json": value, "entities": created, "transcript": transcript, "attempts": attempts,
            "model": model, "instance": instance.name, "cost_yuan": float(cost), "cached": bool(cached and not attempts),
        })
        task_finished(conn, job.task, job.principal)
