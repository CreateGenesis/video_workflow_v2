"""One-off import of v1 data (SQLite + local media folders). Works, entities, links and files only;
v1 jobs, devices and settings are not carried over."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sqlalchemy import select

from . import artifacts, db, graph
from .auth import SYSTEM
from .ontology import types

SKIP_TYPES = {"Workspace", "Work"}
SKIP_LINKS = {"contains", "belongs_to"}


def import_sqlite(path: str, workspace_id: str | None = None) -> dict:
    source = Path(path)
    media_root = source.parent
    legacy = sqlite3.connect(source)
    legacy.row_factory = sqlite3.Row
    rows = [dict(row) | {"data": json.loads(row["data"] or "{}")} for row in legacy.execute("SELECT * FROM entities")]
    links = [dict(row) for row in legacy.execute("SELECT * FROM links")]
    by_id = {row["id"]: row for row in rows}
    owner: dict[str, str] = {}
    for row in rows:
        if row["data"].get("work_id"):
            owner[row["id"]] = row["data"]["work_id"]
    for link in links:
        if link["name"] == "belongs_to":
            owner.setdefault(link["source_id"], link["target_id"])
    changed = True
    while changed:
        changed = False
        for link in links:
            if link["name"] in SKIP_LINKS:
                continue
            if link["source_id"] in owner and link["target_id"] not in owner and link["target_id"] in by_id:
                owner[link["target_id"]] = owner[link["source_id"]]
                changed = True
    report = {"works": 0, "entities": 0, "links": 0, "files": 0, "skipped": []}
    with db.tx() as conn:
        if not workspace_id:
            workspace_id = conn.execute(select(db.workspaces.c.id).order_by(db.workspaces.c.created_at).limit(1)).scalar()
        work_map: dict[str, str] = {}
        for row in rows:
            if row["type"] == "Work":
                work = graph.create_work(conn, SYSTEM, workspace_id, f"{row['data'].get('title') or row['id']}（v1 导入）",
                                         kind=row["data"].get("kind", ""), brief=row["data"].get("brief", ""))
                work_map[row["id"]] = work["id"]
                report["works"] += 1
        orphan_work = None
        entity_map: dict[str, str] = {}
        for row in rows:
            if row["type"] in SKIP_TYPES:
                continue
            if row["type"] not in types():
                report["skipped"].append(f"{row['id']}：v2 没有类型 {row['type']}")
                continue
            target_work = work_map.get(owner.get(row["id"], ""))
            if not target_work:
                if not orphan_work:
                    orphan_work = graph.create_work(conn, SYSTEM, workspace_id, "v1 未归属实体")["id"]
                target_work = orphan_work
            artifact_id = None
            key = row.get("object_key") or ""
            if key and not key.startswith("http"):
                file_path = media_root / key
                if file_path.is_file():
                    artifact_id = artifacts.store_file(conn, workspace_id, file_path, prefix="legacy",
                                                       label=row["data"].get("title") or file_path.name)["id"]
                    report["files"] += 1
            data = {k: v for k, v in row["data"].items() if k not in {"work_id"}}
            data.setdefault("title", row["id"])
            try:
                entity = graph.add_entity(conn, SYSTEM, target_work, row["type"], data, artifact_id=artifact_id)
            except graph.GraphError as exc:
                report["skipped"].append(f"{row['id']}：{exc}")
                continue
            entity_map[row["id"]] = entity["id"]
            report["entities"] += 1
        for link in links:
            if link["name"] in SKIP_LINKS or link["source_id"] not in entity_map or link["target_id"] not in entity_map:
                continue
            source = graph.get_entity(conn, entity_map[link["source_id"]])
            target = graph.get_entity(conn, entity_map[link["target_id"]])
            if source["work_id"] != target["work_id"]:
                report["skipped"].append(f"关系 {link['id']} 跨作品，没有导入")
                continue
            try:
                graph.add_link(conn, SYSTEM, source["work_id"], link["name"], source["id"], target["id"], link.get("note") or "")
                report["links"] += 1
            except (graph.GraphError, graph.NotFound) as exc:
                report["skipped"].append(f"关系 {link['id']}：{exc}")
    return report
