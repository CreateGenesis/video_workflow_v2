"""Turn a model's JSON into ontology entities and links, in memory (to check) or in the database."""

from __future__ import annotations

import copy

from ..ontology import entity_errors, relation_errors
from .template import Scope


class MemoryGraph:
    """Entities created during a dry run or a pre-check. Falls back to `base` for existing nodes."""

    def __init__(self, base=None, asset_node=None):
        self.base = base
        self.asset_node = asset_node
        self.entities: dict[str, dict] = {}
        self.links: list[dict] = []
        self._counter = 0

    def get(self, node_id: str) -> dict:
        if node_id in self.entities:
            return self.entities[node_id]
        if node_id.startswith("asset:") and self.asset_node:
            return self.asset_node(node_id)
        if self.base is None:
            raise LookupError(f"没有这个实体：{node_id}")
        return self.base.get(node_id)

    def linked(self, source_id: str, name: str) -> list[dict]:
        found = [{**self.get(link["target"]), "note": link["note"]}
                 for link in self.links if link["source"] == source_id and link["name"] == name]
        if source_id not in self.entities and self.base is not None:
            found = self.base.linked(source_id, name) + found
        return found

    def add_entity(self, type_name: str, data: dict, artifact_id: str | None = None) -> str:
        self._counter += 1
        node_id = f"{type_name.lower()}_{self._counter:016x}"
        ord_value = sum(1 for node in self.entities.values() if node["type"] == type_name)
        self.entities[node_id] = {"id": node_id, "kind": "entity", "type": type_name, "data": dict(data),
                                  "artifact_id": artifact_id, "ord": ord_value}
        return node_id

    def add_link(self, name: str, source_id: str, target: str, note: str = "") -> list[str]:
        problems = relation_errors(name, self.get(source_id)["type"], self.get(target)["type"])
        if not problems:
            self.links.append({"name": name, "source": source_id, "target": target, "note": note})
        return problems


class MemorySink:
    def __init__(self, graph: MemoryGraph):
        self.graph = graph

    def add_entity(self, type_name: str, data: dict) -> str:
        return self.graph.add_entity(type_name, data)

    def add_link(self, name: str, source_id: str, target: str, note: str) -> list[str]:
        return self.graph.add_link(name, source_id, target, note)


class DbSink:
    def __init__(self, conn, principal, work_id: str, run_id: str | None = None):
        self.conn = conn
        self.principal = principal
        self.work_id = work_id
        self.run_id = run_id

    def add_entity(self, type_name: str, data: dict) -> str:
        from .. import graph

        return graph.add_entity(self.conn, self.principal, self.work_id, type_name, data, run_id=self.run_id)["id"]

    def add_link(self, name: str, source_id: str, target: str, note: str) -> list[str]:
        from .. import graph

        graph.add_link(self.conn, self.principal, self.work_id, name, source_id, target, note)
        return []


def materialize(rules: dict, payload: dict, sink, scope: Scope) -> tuple[dict[str, list[str]], list[str]]:
    """Returns ({field: [entity ids]}, problems). Problems are phrased for the model to fix."""
    created: dict[str, list[str]] = {}
    problems: list[str] = []
    if not isinstance(payload, dict):
        return created, ["输出必须是 JSON 对象"]
    for field_name, rule in rules.items():
        value = payload.get(field_name)
        if value is None:
            problems.append(f"输出缺少字段 {field_name}")
            continue
        items = value if isinstance(value, list) else [value]
        ids = []
        for index, item in enumerate(items):
            label = f"{field_name}[{index}]" if isinstance(value, list) else field_name
            entity_id = _one(rule, item, sink, scope, problems, label)
            if entity_id:
                ids.append(entity_id)
        created[field_name] = ids
    return created, problems


def _one(rule: dict, item, sink, scope: Scope, problems: list[str], label: str) -> str | None:
    if not isinstance(item, dict):
        problems.append(f"{label} 必须是对象")
        return None
    children = rule.get("children") or {}
    data = {key: copy.deepcopy(value) for key, value in item.items() if key not in children and value is not None}
    item_scope = Scope(run=scope.run, spec=scope.spec, graph=scope.graph, asset_lookup=scope.asset_lookup,
                       node_output=scope.node_output, item=item, item_index=scope.item_index)
    for field_name, template in (rule.get("fields") or {}).items():
        data[field_name] = item_scope.render(template)
    issues = entity_errors(rule["type"], data)
    if issues:
        problems.extend(f"{label}：{issue}" for issue in issues)
        return None
    entity_id = sink.add_entity(rule["type"], data)
    for link in rule.get("links") or []:
        for target in item_scope.targets(link["to"]):
            problems.extend(f"{label}：{issue}" for issue in sink.add_link(link["name"], entity_id, target, link.get("note", "")))
    for child_name, child_rule in children.items():
        value = item.get(child_name)
        if value is None:
            problems.append(f"{label} 缺少 {child_name}")
            continue
        child_items = value if isinstance(value, list) else [value]
        for index, child in enumerate(child_items):
            child_label = f"{label}.{child_name}[{index}]" if isinstance(value, list) else f"{label}.{child_name}"
            child_id = _one(child_rule, child, sink, scope, problems, child_label)
            if child_id:
                problems.extend(f"{child_label}：{issue}"
                                for issue in sink.add_link(child_rule["parent_link"], entity_id, child_id, ""))
    return entity_id
