"""Load the plain-text ontology and validate instances against it."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"

ROLES = {"身份", "空间", "细节", "风格", "分镜", "音色", "情感", "首帧", "尾帧"}


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
        relations[name] = item
    return relations


def load_constraints(path: Path | None = None) -> list[str]:
    text = (path or ONTOLOGY / "constraints.md").read_text(encoding="utf-8")
    return [re.sub(r"^-\s*", "", line).strip() for line in text.splitlines() if line.startswith("- ")]


def document() -> dict:
    return {
        "types": load_types(),
        "relations": load_relations(),
        "constraints": load_constraints(),
    }
