"""Workflow spec v1: structural checks (JSON Schema), dependency analysis, and semantic checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy.engine import Connection

from ..ontology import relation_errors, relations, types

SCHEMA_PATH = Path(__file__).with_name("workflow.v1.schema.json")
TOKEN = re.compile(r"\{\{\s*([A-Za-z_][\w-]*(?:\.[\w-]+)*)\s*\}\}")
CONTEXT_ROOTS = {"inputs", "assets", "run", "item"}
KINDS = ("llm", "image", "video", "tts", "music", "check", "edit", "gate")


@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _path(error) -> str:
    parts = []
    for item in error.absolute_path:
        parts.append(f"[{item}]" if isinstance(item, int) else f".{item}")
    return "".join(parts).lstrip(".") or "(根)"


def structure_errors(spec: dict) -> list[str]:
    root = schema()
    validator = Draft202012Validator(root)
    errors = []
    for error in sorted(validator.iter_errors(spec), key=lambda item: list(item.absolute_path)):
        path = list(error.absolute_path)
        if len(path) == 2 and path[0] == "nodes" and error.validator == "oneOf":
            node = spec["nodes"][path[1]]
            kind = node.get("kind") if isinstance(node, dict) else None
            if kind in KINDS:
                sub = Draft202012Validator({**root["$defs"][f"{kind}Node"], "$defs": root["$defs"]})
                for inner in sub.iter_errors(node):
                    inner_path = "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in inner.absolute_path)
                    errors.append(f"nodes[{path[1]}]{inner_path}（{node.get('id', '?')}）：{inner.message}")
                continue
            errors.append(f"nodes[{path[1]}]：kind 只能是 {', '.join(KINDS)}")
            continue
        errors.append(f"{_path(error)}：{error.message}")
    return errors


def template_refs(value) -> set[str]:
    """Every {{path}} inside strings, lists and dicts."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(match.group(1) for match in TOKEN.finditer(value))
    elif isinstance(value, list):
        for item in value:
            found |= template_refs(item)
    elif isinstance(value, dict):
        for item in value.values():
            found |= template_refs(item)
    return found


def _node_paths(node: dict) -> list[str]:
    paths = []
    if node.get("for_each"):
        paths.append(node["for_each"])
    if node.get("kind") == "edit":
        if node.get("clips"):
            paths.append(node["clips"])
        for op in node.get("ops", []):
            for key in ("music", "narration", "lines"):
                if op.get(key):
                    paths.append(op[key])
    return paths


@dataclass
class Analysis:
    nodes: dict[str, dict] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    deps: dict[str, set[str]] = field(default_factory=dict)
    roots: dict[str, tuple | None] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def analyze(spec: dict) -> Analysis:
    result = Analysis()
    for node in spec.get("nodes", []):
        if node["id"] in result.nodes:
            result.errors.append(f"节点 id 重复：{node['id']}")
        result.nodes[node["id"]] = node
    for node_id, node in result.nodes.items():
        deps = set(node.get("after", []))
        refs = {ref.split(".", 1)[0] for ref in template_refs({k: v for k, v in node.items() if k not in {"id", "kind"}})}
        refs |= {path.split(".", 1)[0] for path in _node_paths(node)}
        for ref in refs - CONTEXT_ROOTS:
            deps.add(ref)
        for dep in sorted(deps):
            if dep not in result.nodes:
                result.errors.append(f"节点 {node_id} 引用了不存在的节点 {dep}")
        deps.discard(node_id)
        result.deps[node_id] = {dep for dep in deps if dep in result.nodes}
        if node.get("kind") == "gate":
            for shown in node.get("show", []):
                if shown not in result.nodes:
                    result.errors.append(f"闸门 {node_id} 要展示的节点 {shown} 不存在")
    remaining = {node_id: set(deps) for node_id, deps in result.deps.items()}
    while remaining:
        ready = sorted(node_id for node_id, deps in remaining.items() if not deps)
        if not ready:
            result.errors.append("步骤之间有循环依赖：" + "、".join(sorted(remaining)))
            break
        for node_id in ready:
            result.order.append(node_id)
            remaining.pop(node_id)
        for deps in remaining.values():
            deps.difference_update(ready)
    order_index = {node_id: index for index, node_id in enumerate(result.order)}
    for node_id in sorted(result.nodes, key=lambda item: order_index.get(item, 999)):
        result.roots[node_id] = _root(result, node_id, set())
    for path in spec.get("outputs", {}).values():
        head = path.split(".", 1)[0]
        if head not in CONTEXT_ROOTS and head not in result.nodes:
            result.errors.append(f"outputs 引用了不存在的节点 {head}")
    return result


def _root(result: Analysis, node_id: str, seen: set[str]) -> tuple | None:
    node = result.nodes[node_id]
    path = node.get("for_each")
    if not path:
        return None
    head, _, rest = path.partition(".")
    if head == "inputs":
        return ("inputs", rest)
    if head not in result.nodes or head in seen:
        return None
    if rest:
        return ("node", head, rest)
    upstream = _root(result, head, seen | {node_id})
    if upstream is None:
        result.errors.append(f"节点 {node_id} 的 for_each 指向 {head}，但 {head} 不是逐条执行的节点")
    return upstream


def same_items(analysis: Analysis, a: str, b: str) -> bool:
    return analysis.roots.get(a) is not None and analysis.roots.get(a) == analysis.roots.get(b)


def semantic_check(conn: Connection, workspace_id: str, spec: dict, *, check_env: bool = False) -> dict:
    """Errors block publishing; warnings are shown to the reviewer."""
    from .. import assets as asset_lib
    from ..providers.instances import resolve as resolve_provider

    errors: list[str] = []
    warnings: list[str] = []
    analysis = analyze(spec)
    errors += analysis.errors
    try:
        Draft202012Validator.check_schema(spec.get("inputs", {}))
    except SchemaError as exc:
        errors.append(f"inputs 不是合法的 JSON Schema：{exc.message}")
    resolved: dict[str, dict] = {}
    for alias, ref in (spec.get("assets") or {}).items():
        try:
            resolved[alias] = asset_lib.resolve(conn, workspace_id, ref)
        except asset_lib.AssetError as exc:
            errors.append(f"assets.{alias}：{exc}")

    def asset_kind(template: str) -> str | None:
        match = TOKEN.fullmatch(template.strip()) if isinstance(template, str) else None
        if not match or not match.group(1).startswith("assets."):
            return None
        alias = match.group(1).split(".")[1]
        return resolved[alias]["kind"] if alias in resolved else None

    for node_id in analysis.order:
        node = analysis.nodes[node_id]
        kind = node["kind"]
        for ref in template_refs(node):
            parts = ref.split(".")
            if parts[0] == "assets" and (len(parts) < 2 or parts[1] not in (spec.get("assets") or {})):
                errors.append(f"{node_id} 引用了未声明的素材 {ref}")
            if parts[0] == "inputs" and parts[1:] and parts[1] not in spec.get("inputs", {}).get("properties", {}):
                errors.append(f"{node_id} 引用了未声明的输入 {ref}")
            if parts[0] == "item" and not node.get("for_each"):
                errors.append(f"{node_id} 没有 for_each，不能用 {{{{{ref}}}}}")
        if kind in {"llm", "image", "video", "tts", "music"}:
            instances = resolve_provider(conn, node["provider"], kind)
            if not instances:
                errors.append(f"{node_id}：没有可用的 {kind} 供应商实例 {node['provider']}")
            for instance in instances:
                if not instance.retry_safe and int((node.get("retry") or {}).get("max_attempts", 1)) > 1:
                    errors.append(f"{node_id}：{instance.name} 按次计费且不可安全重试，retry.max_attempts 只能是 1")
                if kind == "video" and instance.protocol == "comfyui" and not node.get("template"):
                    errors.append(f"{node_id}：ComfyUI 供应商必须指定 template")
            if kind == "video" and node.get("template"):
                if asset_kind(node["template"]) not in (None, "comfy_template"):
                    errors.append(f"{node_id}.template 必须指向 comfy_template 素材")
                if check_env:
                    from ..providers import adapter_for

                    template_alias = TOKEN.fullmatch(node["template"].strip())
                    template = resolved.get(template_alias.group(1).split(".")[1]) if template_alias else None
                    for instance in instances:
                        missing = adapter_for(instance).check_template((template or {}).get("data") or {})
                        if missing:
                            warnings.append(f"{node_id}：{instance.name} 缺少 {'、'.join(missing)}")
        if kind == "llm":
            schema_ref = node.get("output_schema")
            if isinstance(schema_ref, str) and asset_kind(schema_ref) not in (None, "schema"):
                errors.append(f"{node_id}.output_schema 必须指向 schema 素材")
            for field_name, rule in (node.get("materialize") or {}).items():
                errors += _rule_errors(node_id, field_name, rule, resolved, spec)
        if kind == "check" and node.get("on_fail") == "rerun_upstream":
            upstream = node["for_each"].split(".", 1)[0]
            if analysis.nodes.get(upstream, {}).get("kind") not in {"video", "image", "tts", "music"}:
                errors.append(f"{node_id}：rerun_upstream 只能检查生成节点的产物")
        if kind == "video" and node.get("continuity") == "previous_last_frame" and not node.get("for_each"):
            errors.append(f"{node_id}：衔接上一镜需要 for_each")
    if not any(node["kind"] == "gate" for node in analysis.nodes.values()):
        warnings.append("没有闸门：发起后全程自动执行，不会停下来等人审")
    return {"errors": errors, "warnings": warnings, "order": analysis.order}


def _rule_errors(node_id: str, field_name: str, rule: dict, resolved: dict, spec: dict) -> list[str]:
    errors = []
    type_name = rule["type"]
    if type_name not in types():
        errors.append(f"{node_id}.materialize.{field_name}：没有类型 {type_name}")
        return errors
    for link in rule.get("links", []):
        if link["name"] not in relations():
            errors.append(f"{node_id}.materialize.{field_name}：没有关系 {link['name']}")
            continue
        target = link["to"].strip()
        match = TOKEN.fullmatch(target)
        target_type = None
        if match and match.group(1).startswith("assets."):
            alias = match.group(1).split(".")[1]
            target_type = resolved.get(alias, {}).get("kind")
        elif match and match.group(1).startswith("inputs."):
            field_spec = spec.get("inputs", {}).get("properties", {}).get(match.group(1).split(".")[1], {})
            if (field_spec.get("items") or field_spec).get("format") == "asset-upload":
                target_type = "Reference"
        if target_type:
            for problem in relation_errors(link["name"], type_name, target_type):
                errors.append(f"{node_id}.materialize.{field_name}：{problem}")
    for child_name, child in (rule.get("children") or {}).items():
        for problem in relation_errors(child["parent_link"], type_name, child["type"]):
            errors.append(f"{node_id}.materialize.{field_name}.{child_name}：{problem}")
        errors += _rule_errors(node_id, f"{field_name}.{child_name}", child, resolved, spec)
    return errors
