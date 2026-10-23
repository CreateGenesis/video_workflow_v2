"""{{path}} templates. One syntax, no logic: values come from inputs, assets, run, item, or a node.

How a value renders depends on where it is used:
- text: entities and assets render as their title (prompt assets as their text), lists join with "、";
- targets (links.to, references, attach_to): entities render as ids, assets as asset:name@version,
  lists expand to several targets;
- schemas (output_schema): a schema asset renders as its JSON Schema.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from .spec import TOKEN

ENTITY_ID = re.compile(r"^[a-z]+_[0-9a-f]{16}$")


class TemplateError(ValueError):
    pass


@dataclass(frozen=True)
class EntityRef:
    id: str


@dataclass(frozen=True)
class AssetRef:
    ref: str
    kind: str
    data: dict
    title: str
    artifact_id: str | None


class Scope:
    """Values visible to one task. `graph` answers get(id); `node_output` returns a node's result."""

    def __init__(
        self,
        *,
        run: dict,
        spec: dict,
        graph,
        asset_lookup: Callable[[str], dict],
        node_output: Callable[[str], Any],
        item: Any = None,
        item_index: int = 0,
    ):
        self.run = run
        self.spec = spec
        self.graph = graph
        self.asset_lookup = asset_lookup
        self.node_output = node_output
        self.item = item
        self.item_index = item_index

    def _asset(self, alias: str) -> AssetRef:
        ref = (self.spec.get("assets") or {}).get(alias)
        if not ref:
            raise TemplateError(f"没有声明素材 {alias}")
        version = self.asset_lookup(ref)
        return AssetRef(ref=ref, kind=version["kind"], data=dict(version.get("data") or {}),
                        title=version.get("title") or version["name"], artifact_id=version.get("artifact_id"))

    def _field(self, value: Any, field: str) -> Any:
        if isinstance(value, list):
            return [self._field(item, field) for item in value]
        if isinstance(value, EntityRef):
            if field == "id":
                return value.id
            return self.graph.get(value.id)["data"].get(field)
        if isinstance(value, AssetRef):
            return value.data.get(field)
        if isinstance(value, dict):
            return value.get(field)
        raise TemplateError(f"{value!r} 没有字段 {field}")

    def lookup(self, path: str) -> Any:
        head, *rest = path.split(".")
        if head == "inputs":
            if not rest:
                raise TemplateError("inputs 后面要写字段名")
            uploads = (self.run.get("context") or {}).get("uploads") or {}
            if rest[0] in uploads:
                value: Any = [EntityRef(entity_id) for entity_id in uploads[rest[0]]]
            else:
                value = (self.run.get("inputs") or {}).get(rest[0])
            rest = rest[1:]
        elif head == "assets":
            if not rest:
                raise TemplateError("assets 后面要写别名")
            value = self._asset(rest[0])
            rest = rest[1:]
        elif head == "run":
            value = {"id": self.run.get("id"), "batch_id": self.run.get("batch_id"),
                     "created_at": str(self.run.get("created_at") or "")}
        elif head == "item":
            if rest and rest[0] == "index":
                return self.item_index
            value = self.item
        else:
            value = self.node_output(head)
            if rest and isinstance(value, dict) and rest[0] in (value.get("entities") or {}):
                value = [EntityRef(entity_id) for entity_id in value["entities"][rest[0]]]
                rest = rest[1:]
            elif isinstance(value, dict) and "json" in value:
                value = value["json"]
        for part in rest:
            value = self._field(value, part)
        return value

    def text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "、".join(part for part in (self.text(item) for item in value) if part)
        if isinstance(value, EntityRef):
            data = self.graph.get(value.id)["data"]
            return str(data.get("title") or data.get("text") or value.id)
        if isinstance(value, AssetRef):
            if value.kind == "prompt":
                return str(value.data.get("text") or "")
            if value.kind == "schema":
                return json.dumps(value.data.get("schema") or {}, ensure_ascii=False)
            return value.title
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def render(self, template: str) -> str:
        return TOKEN.sub(lambda match: self.text(self.lookup(match.group(1))), template or "")

    def targets(self, template: str) -> list[str]:
        """Entity ids and asset refs a template points at. Plain text is not allowed here."""
        match = TOKEN.fullmatch((template or "").strip())
        if not match:
            raise TemplateError(f"这里只能写一个 {{{{路径}}}}：{template}")
        found: list[str] = []

        def collect(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, EntityRef):
                found.append(value.id)
            elif isinstance(value, AssetRef):
                found.append(value.ref)
            elif isinstance(value, str) and (value.startswith("asset:") or ENTITY_ID.match(value)):
                found.append(value)
            else:
                raise TemplateError(f"{template} 不是实体或素材")

        collect(self.lookup(match.group(1)))
        return found

    def artifacts(self, template: str) -> list[str]:
        """Files behind the targets (for image references)."""
        result = []
        for target in self.targets(template):
            node = self.graph.get(target)
            if node.get("artifact_id"):
                result.append(node["artifact_id"])
        return result

    def schema(self, value: Any) -> dict:
        if isinstance(value, dict):
            return value
        match = TOKEN.fullmatch((value or "").strip())
        if not match:
            raise TemplateError("output_schema 要写成 {{assets.别名}} 或直接写 JSON Schema")
        resolved = self.lookup(match.group(1))
        if isinstance(resolved, AssetRef) and resolved.kind == "schema":
            return resolved.data.get("schema") or {}
        if isinstance(resolved, dict):
            return resolved
        raise TemplateError("output_schema 必须指向 schema 素材")

    def asset_data(self, template: str) -> dict:
        match = TOKEN.fullmatch((template or "").strip())
        resolved = self.lookup(match.group(1)) if match else None
        if not isinstance(resolved, AssetRef):
            raise TemplateError(f"{template} 不是素材")
        return resolved.data
