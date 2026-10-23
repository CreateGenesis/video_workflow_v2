"""Works and their entity graphs. Ownership is a column, never a relation."""

from __future__ import annotations

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from . import assets, db, events
from .ontology import entity_errors, relation_errors


class GraphError(ValueError):
    pass


class NotFound(LookupError):
    pass


def _actor(principal) -> str:
    return f"{principal.kind}:{principal.id}"


def create_work(
    conn: Connection, principal, workspace_id: str, title: str, *,
    kind: str = "", brief: str = "", origin: str = "explore", run_id: str | None = None,
) -> dict:
    title = (title or "").strip()
    if not title:
        raise GraphError("作品名称不能为空")
    row = {
        "id": db.new_id("work"), "workspace_id": workspace_id, "title": title, "kind": kind or "",
        "brief": brief or "", "origin": origin, "run_id": run_id, "created_by": _actor(principal),
    }
    conn.execute(insert(db.works).values(**row))
    events.record(conn, principal, "work.create", workspace_id=workspace_id, work_id=row["id"],
                  run_id=run_id, target_kind="work", target_id=row["id"], payload={"title": title, "origin": origin})
    return get_work(conn, row["id"])


def get_work(conn: Connection, work_id: str) -> dict | None:
    row = conn.execute(select(db.works).where(db.works.c.id == work_id)).mappings().first()
    return dict(row) if row else None


def require_work(conn: Connection, work_id: str) -> dict:
    work = get_work(conn, work_id)
    if not work or work["archived_at"]:
        raise NotFound(f"没有这个作品：{work_id}")
    return work


def list_works(conn: Connection, workspace_id: str | None = None, origin: str | None = None) -> list[dict]:
    query = select(db.works).where(db.works.c.archived_at.is_(None)).order_by(db.works.c.created_at.desc())
    if workspace_id:
        query = query.where(db.works.c.workspace_id == workspace_id)
    if origin:
        query = query.where(db.works.c.origin == origin)
    return [dict(row) for row in conn.execute(query).mappings()]


def update_work(conn: Connection, principal, work_id: str, fields: dict) -> dict:
    work = require_work(conn, work_id)
    allowed = {key: value for key, value in fields.items() if key in {"title", "kind", "brief"} and value is not None}
    if "title" in allowed and not str(allowed["title"]).strip():
        raise GraphError("作品名称不能为空")
    if allowed:
        conn.execute(update(db.works).where(db.works.c.id == work_id).values(**allowed))
        events.record(conn, principal, "work.update", workspace_id=work["workspace_id"], work_id=work_id,
                      target_kind="work", target_id=work_id, payload=allowed)
    return get_work(conn, work_id)


def archive_work(conn: Connection, principal, work_id: str) -> None:
    work = require_work(conn, work_id)
    conn.execute(update(db.works).where(db.works.c.id == work_id).values(archived_at=db.now()))
    events.record(conn, principal, "work.archive", workspace_id=work["workspace_id"], work_id=work_id,
                  target_kind="work", target_id=work_id)


def get_entity(conn: Connection, entity_id: str) -> dict | None:
    row = conn.execute(
        select(db.entities).where(db.entities.c.id == entity_id, db.entities.c.deleted_at.is_(None))
    ).mappings().first()
    return dict(row) if row else None


def require_entity(conn: Connection, entity_id: str, work_id: str | None = None) -> dict:
    entity = get_entity(conn, entity_id)
    if not entity:
        raise NotFound(f"没有这个实体：{entity_id}")
    if work_id and entity["work_id"] != work_id:
        raise GraphError("这个实体不属于当前作品")
    return entity


def add_entity(
    conn: Connection, principal, work_id: str, type_name: str, data: dict, *,
    artifact_id: str | None = None, ord: int | None = None, run_id: str | None = None,
) -> dict:
    work = require_work(conn, work_id)
    data = dict(data or {})
    problems = entity_errors(type_name, data)
    if problems:
        raise GraphError("；".join(problems))
    if ord is None:
        ord = conn.execute(
            select(func.coalesce(func.max(db.entities.c.ord), -1) + 1)
            .where(db.entities.c.work_id == work_id, db.entities.c.type == type_name)
        ).scalar_one()
    row = {
        "id": db.new_id(type_name.lower()), "work_id": work_id, "type": type_name, "data": data,
        "artifact_id": artifact_id, "ord": ord, "created_by": _actor(principal),
    }
    conn.execute(insert(db.entities).values(**row))
    events.record(conn, principal, "entity.create", workspace_id=work["workspace_id"], work_id=work_id,
                  run_id=run_id or work.get("run_id"), target_kind=type_name, target_id=row["id"],
                  payload={"title": data.get("title", "")})
    return get_entity(conn, row["id"])


def update_entity(conn: Connection, principal, entity_id: str, data: dict, *, merge: bool = True,
                  artifact_id: str | None = None) -> dict:
    entity = require_entity(conn, entity_id)
    merged = {**entity["data"], **(data or {})} if merge else dict(data or {})
    merged = {key: value for key, value in merged.items() if value is not None}
    problems = entity_errors(entity["type"], merged)
    if problems:
        raise GraphError("；".join(problems))
    values = {"data": merged, "updated_at": db.now()}
    if artifact_id:
        values["artifact_id"] = artifact_id
    conn.execute(update(db.entities).where(db.entities.c.id == entity_id).values(**values))
    work = get_work(conn, entity["work_id"])
    changed = sorted(key for key in merged if merged.get(key) != entity["data"].get(key))
    events.record(conn, principal, "entity.update", workspace_id=work["workspace_id"], work_id=work["id"],
                  run_id=work.get("run_id"), target_kind=entity["type"], target_id=entity_id,
                  payload={"fields": changed})
    return get_entity(conn, entity_id)


def delete_entity(conn: Connection, principal, entity_id: str) -> None:
    entity = require_entity(conn, entity_id)
    stamp = db.now()
    conn.execute(update(db.entities).where(db.entities.c.id == entity_id).values(deleted_at=stamp))
    conn.execute(update(db.links).where(
        db.links.c.deleted_at.is_(None),
        or_(db.links.c.source_id == entity_id, and_(db.links.c.target_kind == "entity", db.links.c.target_id == entity_id)),
    ).values(deleted_at=stamp))
    work = get_work(conn, entity["work_id"])
    events.record(conn, principal, "entity.delete", workspace_id=work["workspace_id"], work_id=work["id"],
                  target_kind=entity["type"], target_id=entity_id)


def list_entities(conn: Connection, work_id: str, type_name: str | None = None) -> list[dict]:
    query = select(db.entities).where(db.entities.c.work_id == work_id, db.entities.c.deleted_at.is_(None))
    if type_name:
        query = query.where(db.entities.c.type == type_name)
    query = query.order_by(db.entities.c.type, db.entities.c.ord, db.entities.c.created_at)
    return [dict(row) for row in conn.execute(query).mappings()]


def _target(conn: Connection, workspace_id: str, work_id: str, target: str) -> tuple[str, str, int | None, str]:
    """Returns (kind, id, version, type). Targets are entity ids in this work or asset:name@version."""
    if target.startswith("asset:"):
        version = assets.resolve(conn, workspace_id, target)
        return "asset", version["id"], version["version"], version["kind"]
    entity = get_entity(conn, target)
    if not entity:
        raise NotFound(f"没有这个实体：{target}")
    if entity["work_id"] != work_id:
        raise GraphError("不能连到另一个作品的实体；需要复用请先提升为素材")
    return "entity", entity["id"], None, entity["type"]


def add_link(
    conn: Connection, principal, work_id: str, name: str, source_id: str, target: str, note: str = "",
) -> dict:
    work = require_work(conn, work_id)
    source = require_entity(conn, source_id, work_id)
    kind, target_id, version, target_type = _target(conn, work["workspace_id"], work_id, target)
    problems = relation_errors(name, source["type"], target_type)
    if problems:
        raise GraphError("；".join(problems))
    if name == "shot_with":
        existing = [item for item in links_from(conn, source_id, "shot_with")]
        if existing and not any(item["target_id"] == target_id for item in existing):
            raise GraphError("一条镜头只能有一种运镜（shot_with 最多一条）")
    ord = conn.execute(
        select(func.coalesce(func.max(db.links.c.ord), -1) + 1)
        .where(db.links.c.source_id == source_id, db.links.c.name == name, db.links.c.deleted_at.is_(None))
    ).scalar_one()
    row = {
        "id": db.new_id("link"), "work_id": work_id, "name": name, "source_id": source_id,
        "target_kind": kind, "target_id": target_id, "target_version": version, "note": note or "",
        "ord": ord, "created_by": _actor(principal),
    }
    stmt = pg_insert(db.links).values(**row).on_conflict_do_nothing().returning(db.links.c.id)
    created = conn.execute(stmt).scalar()
    if not created:
        existing = conn.execute(select(db.links).where(
            db.links.c.work_id == work_id, db.links.c.name == name, db.links.c.source_id == source_id,
            db.links.c.target_kind == kind, db.links.c.target_id == target_id,
            func.coalesce(db.links.c.target_version, 0) == (version or 0), db.links.c.deleted_at.is_(None),
        )).mappings().first()
        return {**dict(existing), "duplicate": True}
    events.record(conn, principal, "link.create", workspace_id=work["workspace_id"], work_id=work_id,
                  run_id=work.get("run_id"), target_kind="link", target_id=row["id"],
                  payload={"name": name, "source": source_id, "target": target})
    return {**row, "duplicate": False}


def remove_link(conn: Connection, principal, link_id: str) -> None:
    row = conn.execute(select(db.links).where(db.links.c.id == link_id, db.links.c.deleted_at.is_(None))).mappings().first()
    if not row:
        raise NotFound(f"没有这条关系：{link_id}")
    conn.execute(update(db.links).where(db.links.c.id == link_id).values(deleted_at=db.now()))
    work = get_work(conn, row["work_id"])
    events.record(conn, principal, "link.delete", workspace_id=work["workspace_id"], work_id=work["id"],
                  target_kind="link", target_id=link_id, payload={"name": row["name"]})


def links_from(conn: Connection, source_id: str, name: str | None = None) -> list[dict]:
    query = select(db.links).where(db.links.c.source_id == source_id, db.links.c.deleted_at.is_(None))
    if name:
        query = query.where(db.links.c.name == name)
    return [dict(row) for row in conn.execute(query.order_by(db.links.c.ord, db.links.c.created_at)).mappings()]


def list_links(conn: Connection, work_id: str) -> list[dict]:
    query = select(db.links).where(db.links.c.work_id == work_id, db.links.c.deleted_at.is_(None))
    return [dict(row) for row in conn.execute(query.order_by(db.links.c.created_at)).mappings()]


def entity_node(entity: dict) -> dict:
    return {
        "id": entity["id"], "kind": "entity", "type": entity["type"], "data": dict(entity["data"] or {}),
        "artifact_id": entity.get("artifact_id"), "ord": entity.get("ord", 0),
    }


class DbGraph:
    """Read-only graph view used by compose and the workflow engine."""

    def __init__(self, conn: Connection, workspace_id: str):
        self.conn = conn
        self.workspace_id = workspace_id
        self._assets: dict[tuple[str, int], dict] = {}

    def get(self, node_id: str) -> dict:
        if node_id.startswith("asset:"):
            return assets.as_node(assets.resolve(self.conn, self.workspace_id, node_id))
        return entity_node(require_entity(self.conn, node_id))

    def _asset_node(self, asset_id: str, version: int) -> dict:
        key = (asset_id, version)
        if key not in self._assets:
            asset = self.conn.execute(select(db.assets.c.name).where(db.assets.c.id == asset_id)).scalar_one()
            self._assets[key] = assets.as_node(assets.get_version(self.conn, self.workspace_id, asset, version))
        return self._assets[key]

    def linked(self, source_id: str, name: str) -> list[dict]:
        nodes = []
        for link in links_from(self.conn, source_id, name):
            if link["target_kind"] == "asset":
                node = self._asset_node(link["target_id"], link["target_version"])
            else:
                entity = get_entity(self.conn, link["target_id"])
                if not entity:
                    continue
                node = entity_node(entity)
            nodes.append({**node, "note": link["note"]})
        return nodes


def snapshot(conn: Connection, work_id: str) -> dict:
    """Everything the console needs to draw a work: entities, links, and the library assets they point at."""
    work = require_work(conn, work_id)
    entities = list_entities(conn, work_id)
    links = list_links(conn, work_id)
    graph = DbGraph(conn, work["workspace_id"])
    asset_nodes = {}
    for link in links:
        if link["target_kind"] == "asset":
            node = graph._asset_node(link["target_id"], link["target_version"])
            asset_nodes[node["id"]] = node
            link["target_ref"] = node["id"]
        else:
            link["target_ref"] = link["target_id"]
    return {"work": work, "entities": entities, "links": links, "assets": list(asset_nodes.values())}
