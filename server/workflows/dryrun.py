"""Dry runs. compile: no paid calls (LLM nodes use stored fixtures). llm: real LLM calls, then compile.

The result lists every final video prompt and an itemized cost estimate, so a reviewer can read
exactly what would be sent before anything is spent.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.engine import Connection

from .. import artifacts, assets, graph
from ..compose import compose
from ..providers import adapter_for
from ..providers.base import Usage
from ..providers.instances import resolve as resolve_provider
from .materialize import MemoryGraph, MemorySink, materialize
from .spec import analyze
from .template import EntityRef, Scope

PLACEHOLDER = {"title": "（试跑占位）关键帧", "take": "画面构图和主体位置", "ignore": "占位图本身的内容"}


def compile_run(conn: Connection, workspace_id: str, spec: dict, inputs: dict, fixtures: dict) -> dict:
    base = graph.DbGraph(conn, workspace_id)
    memory = MemoryGraph(base=base, asset_node=base.get)
    uploads = {}
    for field_name, field in (spec.get("inputs") or {}).get("properties", {}).items():
        item_spec = field.get("items") if field.get("type") == "array" else field
        if item_spec and item_spec.get("format") == "asset-upload" and field_name in inputs:
            values = inputs[field_name] if isinstance(inputs[field_name], list) else [inputs[field_name]]
            ids = []
            for artifact_id in values:
                row = artifacts.get(conn, artifact_id) if isinstance(artifact_id, str) else None
                ids.append(memory.add_entity("Reference", {
                    "title": (row or {}).get("label") or field.get("title") or field_name,
                    "role": item_spec.get("x-role") or "身份", "take": "只采用图中的主体外形和标识",
                    "ignore": "不采用背景和光线",
                }, artifact_id=artifact_id))
            uploads[field_name] = ids
    run = {"id": "dryrun", "inputs": inputs, "context": {"uploads": uploads}, "workspace_id": workspace_id}

    def llm_output(node_id: str, scope: Scope) -> tuple[dict, list[str]]:
        fixture = (fixtures or {}).get(node_id)
        if fixture is None:
            return {}, [f"{node_id}：没有试跑样例（fixtures），先跑一次 llm 级试跑或 trial"]
        node = analyze(spec).nodes[node_id]
        created, problems = materialize(node.get("materialize") or {}, fixture, MemorySink(memory), scope)
        return {"json": fixture, "entities": created}, problems

    return _compile(conn, workspace_id, spec, run, memory, llm_output)


def compile_from_run(conn: Connection, run: dict) -> dict:
    """After an llm-level dry run: the LLM outputs are real and already in the run's work."""
    from .runner import current_tasks, get_version

    spec = get_version(conn, run["workflow_id"], run["version"], published_only=False)["spec"]
    base = graph.DbGraph(conn, run["workspace_id"])
    memory = MemoryGraph(base=base, asset_node=base.get)
    outputs = {task["node_id"]: task["output"] for task in current_tasks(conn, run["id"]) if task["kind"] == "llm"}

    def llm_output(node_id: str, scope: Scope) -> tuple[dict, list[str]]:
        return outputs.get(node_id) or {}, [] if node_id in outputs else [f"{node_id} 没有输出"]

    return _compile(conn, run["workspace_id"], spec, run, memory, llm_output)


def _compile(conn, workspace_id: str, spec: dict, run: dict, memory: MemoryGraph, llm_output) -> dict:
    analysis = analyze(spec)
    outputs: dict[str, object] = {}
    prompts, breakdown, problems = [], [], list(analysis.errors)
    total = Decimal("0")

    def node_output(node_id: str):
        return outputs.get(node_id, {})

    def scope(item=None, index: int = 0) -> Scope:
        return Scope(run=run, spec=spec, graph=memory, asset_lookup=lambda ref: assets.resolve(conn, workspace_id, ref),
                     node_output=node_output, item=item, item_index=index)

    def items_for(node: dict) -> list[tuple[int, object]]:
        if not node.get("for_each"):
            return [(0, None)]
        value = scope().lookup(node["for_each"])
        values = value if isinstance(value, list) else ([value] if value is not None else [])
        return list(enumerate(values))

    def charge(node: dict, request: dict, label: str) -> None:
        nonlocal total
        instances = resolve_provider(conn, node["provider"], node["kind"])
        if not instances:
            problems.append(f"{node['id']}：没有可用的供应商 {node['provider']}")
            return
        instance = instances[0]
        usage: list[Usage] = adapter_for(instance).estimate(request)
        amount = sum(Decimal(str(instance.pricing.get(item.unit, 0))) * Decimal(str(item.quantity)) for item in usage)
        total += amount
        breakdown.append({"node": node["id"], "item": label, "provider": instance.name,
                          "usage": [{"unit": item.unit, "quantity": item.quantity} for item in usage],
                          "yuan": float(round(amount, 4))})

    for node_id in analysis.order:
        node = analysis.nodes[node_id]
        kind = node["kind"]
        if kind == "llm":
            output, issues = llm_output(node_id, scope())
            outputs[node_id] = output
            problems += issues
            charge(node, {"system": "", "messages": [{"role": "user", "content": str(output.get("json", ""))}]}, "")
            continue
        per_item = []
        for index, item in items_for(node):
            label = f"{index:03d}" if node.get("for_each") else ""
            item_id = item.id if isinstance(item, EntityRef) else item
            if kind == "image":
                charge(node, {"n": int(node.get("candidates", 1))}, label)
                target = node.get("attach_to")
                if target:
                    for attach in scope(item, index).targets(target):
                        ref = memory.add_entity("Reference", {**PLACEHOLDER, "role": node["role"]})
                        problems += memory.add_link("references", attach, ref, "试跑占位")
                per_item.append({"item": label})
            elif kind == "video":
                resolution = node.get("resolution") or (spec.get("defaults") or {}).get("resolution") or "768p横"
                try:
                    plan = compose(memory, item_id, resolution)
                except (ValueError, LookupError) as exc:
                    problems.append(f"{node_id}[{label}]：{exc}")
                    continue
                prompt = plan["prompt"]
                if node.get("prompt") and node["prompt"] != "compose":
                    prompt = scope(item, index).render(node["prompt"])
                prompts.append({"node": node_id, "item": label, "shot_id": item_id,
                                "title": memory.get(item_id)["data"].get("title"), "prompt": prompt,
                                "duration": plan["duration"], "resolution": resolution, "warnings": plan["warnings"],
                                "references": [ref["title"] for ref in plan["references"]]})
                charge(node, {"duration": plan["duration"], "resolution": resolution}, label)
                per_item.append({"item": label, "shot_id": item_id})
            elif kind in {"tts", "music"}:
                charge(node, {"duration": node.get("duration_seconds")}, label)
                per_item.append({"item": label})
            else:
                per_item.append({"item": label})
        outputs[node_id] = per_item if node.get("for_each") else (per_item[0] if per_item else {})
    budget = Decimal(str((spec.get("budget") or {}).get("max_yuan", 0)))
    if budget and total > budget:
        problems.append(f"估算花费 {round(total, 2)} 元超过预算 {budget} 元")
    return {
        "prompts": prompts,
        "llm": {node_id: output.get("json") for node_id, output in outputs.items()
                if isinstance(output, dict) and "json" in output},
        "estimate_yuan": float(round(total, 4)),
        "breakdown": breakdown,
        "problems": problems,
    }
