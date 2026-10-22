"""Workspace library. Assets are versioned; a published workflow pins exact versions."""

from __future__ import annotations

import re

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Connection

from . import db, events
from .ontology import NON_ENTITY_ASSET_KINDS, entity_errors, types

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
REF_RE = re.compile(r"^asset:([a-z0-9][a-z0-9_-]{0,63})@([1-9][0-9]*)$")


class AssetError(ValueError):
    pass


def parse_ref(ref: str) -> tuple[str, int]:
    match = REF_RE.match(ref or "")
    if not match:
        raise AssetError(f"素材引用要写成 asset:名称@版本：{ref}")
    return match.group(1), int(match.group(2))


def format_ref(name: str, version: int) -> str:
    return f"asset:{name}@{version}"


def _check(kind: str, data: dict, artifact_id: str | None) -> None:
    if kind in types():
        problems = entity_errors(kind, data)
        if problems:
            raise AssetError("；".join(problems))
        return
    if kind not in NON_ENTITY_ASSET_KINDS:
        raise AssetError(f"素材类型只能是本体类型或 {', '.join(sorted(NON_ENTITY_ASSET_KINDS))}")
    if kind == "prompt" and not str(data.get("text") or "").strip():
        raise AssetError("提示模板素材需要 text")
    if kind == "schema":
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError

        schema = data.get("schema")
        if not isinstance(schema, dict):
            raise AssetError("输出 schema 素材需要 schema 对象")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise AssetError(f"schema 不合法：{exc.message}") from exc
    if kind == "comfy_template":
        if not isinstance(data.get("graph"), dict) or not isinstance(data.get("bindings"), dict):
            raise AssetError("ComfyUI 模板需要 graph 和 bindings")
        if not data.get("outputs"):
            raise AssetError("ComfyUI 模板需要 outputs（输出节点 id）")
    if kind == "media" and not artifact_id:
        raise AssetError("媒体素材需要文件")


def get_asset(conn: Connection, workspace_id: str, name: str) -> dict | None:
    row = conn.execute(
        select(db.assets).where(db.assets.c.workspace_id == workspace_id, db.assets.c.name == name)
    ).mappings().first()
    return dict(row) if row else None


def _latest(conn: Connection, asset_id: str) -> int:
    return conn.execute(
        select(func.coalesce(func.max(db.asset_versions.c.version), 0)).where(db.asset_versions.c.asset_id == asset_id)
    ).scalar_one()


def create_or_version(
    conn: Connection,
    principal,
    workspace_id: str,
    name: str,
    kind: str,
    data: dict,
    *,
    title: str = "",
    artifact_id: str | None = None,
    note: str = "",
) -> dict:
    """Create the asset on first use, otherwise append a new version. Returns the new version."""
    if not NAME_RE.match(name or ""):
        raise AssetError("素材名只能用小写字母、数字、- 和 _，最长 64")
    _check(kind, data, artifact_id)
    asset = get_asset(conn, workspace_id, name)
    if asset and asset["kind"] != kind:
        raise AssetError(f"素材 {name} 已经是 {asset['kind']} 类型")
    if not asset:
        asset = {
            "id": db.new_id("asset"),
            "workspace_id": workspace_id,
            "name": name,
            "kind": kind,
            "title": title or str(data.get("title") or name),
            "created_by": f"{principal.kind}:{principal.id}",
        }
        conn.execute(insert(db.assets).values(**asset))
    version = _latest(conn, asset["id"]) + 1
    conn.execute(insert(db.asset_versions).values(
        asset_id=asset["id"], version=version, data=data, artifact_id=artifact_id, note=note,
        created_by=f"{principal.kind}:{principal.id}",
    ))
    events.record(
        conn, principal, "asset.version", workspace_id=workspace_id, target_kind="asset",
        target_id=format_ref(name, version), payload={"kind": kind, "note": note},
    )
    return get_version(conn, workspace_id, name, version)


def get_version(conn: Connection, workspace_id: str, name: str, version: int) -> dict | None:
    row = conn.execute(
        select(db.assets, db.asset_versions.c.version, db.asset_versions.c.data,
               db.asset_versions.c.artifact_id, db.asset_versions.c.note,
               db.asset_versions.c.created_at.label("version_created_at"),
               db.asset_versions.c.created_by.label("version_created_by"))
        .join(db.asset_versions, db.asset_versions.c.asset_id == db.assets.c.id)
        .where(db.assets.c.workspace_id == workspace_id, db.assets.c.name == name,
               db.asset_versions.c.version == version)
    ).mappings().first()
    if not row:
        return None
    item = dict(row)
    item["ref"] = format_ref(name, version)
    return item


def resolve(conn: Connection, workspace_id: str, ref: str) -> dict:
    name, version = parse_ref(ref)
    found = get_version(conn, workspace_id, name, version)
    if not found:
        raise AssetError(f"素材库里没有 {ref}")
    return found


def list_assets(conn: Connection, workspace_id: str, kind: str | None = None) -> list[dict]:
    latest = (
        select(db.asset_versions.c.asset_id, func.max(db.asset_versions.c.version).label("latest"))
        .group_by(db.asset_versions.c.asset_id).subquery()
    )
    query = (
        select(db.assets, latest.c.latest)
        .join(latest, latest.c.asset_id == db.assets.c.id)
        .where(db.assets.c.workspace_id == workspace_id, db.assets.c.archived.is_(False))
        .order_by(db.assets.c.kind, db.assets.c.name)
    )
    if kind:
        query = query.where(db.assets.c.kind == kind)
    return [dict(row) for row in conn.execute(query).mappings()]


def versions(conn: Connection, asset_id: str) -> list[dict]:
    rows = conn.execute(
        select(db.asset_versions).where(db.asset_versions.c.asset_id == asset_id).order_by(db.asset_versions.c.version)
    ).mappings()
    return [dict(row) for row in rows]


def as_node(version: dict) -> dict:
    """Assets join a work's graph as read-only nodes."""
    data = dict(version.get("data") or {})
    data.setdefault("title", version.get("title") or version.get("name"))
    return {
        "id": version["ref"],
        "kind": "asset",
        "type": version["kind"],
        "data": data,
        "artifact_id": version.get("artifact_id"),
        "asset": version["name"],
        "version": version["version"],
    }
