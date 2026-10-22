"""Load the plain-text ontology and validate instances against it."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"

ROLES = {"身份", "空间", "细节", "风格", "分镜", "音色", "情感", "首帧", "尾帧"}
RESOLUTIONS = ("480p横", "480p竖", "768p横", "768p竖", "480p(1:1)", "768p(1:1)")
NON_ENTITY_ASSET_KINDS = {"prompt", "schema", "comfy_template", "media"}


def _sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    name = ""
    lines: list[str] = []
    for raw in text.splitlines():
        if raw.startswith("## "):
            if name:
                sections.append((name, lines))
            name = raw[3:].strip()
            lines = []
        else:
            lines.append(raw)
    if name:
        sections.append((name, lines))
    return sections


def load_types(path: Path | None = None) -> dict[str, dict]:
    text = (path or ONTOLOGY / "types.md").read_text(encoding="utf-8")
    types: dict[str, dict] = {}
    for name, lines in _sections(text):
        fields = []
        label = name
        summary = ""
        for line in lines:
            if line.startswith("label:"):
                label = line.split(":", 1)[1].strip()
            elif line.startswith("summary:"):
                summary = line.split(":", 1)[1].strip()
            elif line.startswith("field "):
                parts = line.split()
                fields.append({
                    "name": parts[1],
                    "required": "必填" in line,
                    "label": line.split(" ", 3)[-1] if len(parts) > 3 else parts[1],
                })
        types[name] = {"name": name, "label": label, "summary": summary, "fields": fields}
    return types


def load_relations(path: Path | None = None) -> dict[str, dict]:
    text = (path or ONTOLOGY / "relations.md").read_text(encoding="utf-8")
    relations: dict[str, dict] = {}
    for name, lines in _sections(text):
        item = {"name": name, "from": "", "to": "", "label": name}
        for line in lines:
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            item[key.strip()] = value.strip()
        item["from_types"] = [part.strip() for part in item["from"].split(",") if part.strip()]
        item["to_types"] = [part.strip() for part in item["to"].split(",") if part.strip()]
        relations[name] = item
    return relations


def load_constraints(path: Path | None = None) -> list[str]:
    text = (path or ONTOLOGY / "constraints.md").read_text(encoding="utf-8")
    return [re.sub(r"^-\s*", "", line).strip() for line in text.splitlines() if line.startswith("- ")]


@lru_cache(maxsize=1)
def types() -> dict[str, dict]:
    return load_types()


@lru_cache(maxsize=1)
def relations() -> dict[str, dict]:
    return load_relations()


def document() -> dict:
    return {
        "types": load_types(),
        "relations": load_relations(),
        "constraints": load_constraints(),
        "roles": sorted(ROLES),
        "resolutions": list(RESOLUTIONS),
    }


def entity_errors(type_name: str, data: dict) -> list[str]:
    known = types()
    if type_name not in known:
        return [f"没有这个类型：{type_name}"]
    problems = []
    for field in known[type_name]["fields"]:
        if field["required"] and data.get(field["name"]) in (None, "", []):
            problems.append(f"{type_name}.{field['name']} 必填（{field['label']}）")
    if type_name == "Reference" and data.get("role") and data["role"] not in ROLES:
        problems.append(f"参考用途只能是：{'、'.join(sorted(ROLES))}")
    if type_name == "Shot" and data.get("duration") not in (None, ""):
        try:
            duration = int(data["duration"])
        except (TypeError, ValueError):
            duration = 0
        if not 1 <= duration <= 15 or str(data["duration"]).strip() != str(duration):
            problems.append("Shot.duration 必须是 1 到 15 的整数")
    if type_name == "Shot" and isinstance(data.get("paragraphs"), list) and len(data["paragraphs"]) > 4:
        problems.append("Shot.paragraphs 最多四拍")
    return problems


def relation_errors(name: str, from_type: str, to_type: str) -> list[str]:
    known = relations()
    if name not in known:
        return [f"没有这个关系：{name}"]
    item = known[name]
    problems = []
    if item["from_types"] and from_type not in item["from_types"]:
        problems.append(f"{name} 的起点只能是 {item['from']}，不能是 {from_type}")
    if item["to_types"] and to_type not in item["to_types"]:
        problems.append(f"{name} 的终点只能是 {item['to']}，不能是 {to_type}")
    return problems
