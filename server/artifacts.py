"""Every media file is an artifact row plus one object. Rows record size, hash, shape and lineage."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from . import db
from .security import media_url
from .storage import get_store, guess_mime

KINDS = {"image", "video", "audio", "sheet", "frame", "document", "other"}


def kind_for(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    return "other"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _shape(path: Path, kind: str) -> dict:
    if kind not in {"image", "video", "audio", "sheet", "frame"}:
        return {}
    from .media import MediaError, probe

    try:
        info = probe(path)
    except (MediaError, OSError, ValueError):
        return {}
    shape = {"width": info.get("width"), "height": info.get("height")}
    if kind in {"video", "audio"}:
        shape["duration"] = info.get("duration") or None
    return shape


def store_file(
    conn: Connection,
    workspace_id: str,
    path: Path,
    *,
    prefix: str,
    kind: str = "",
    mime: str = "",
    label: str = "",
    produced_by_task: str | None = None,
    derived_from: str | None = None,
    source_url: str = "",
) -> dict:
    """Upload a local file and record it. The object key is ws/<workspace>/<prefix>/<artifact id><suffix>."""
    mime = mime or guess_mime(path.name)
    kind = kind or kind_for(mime)
    artifact_id = db.new_id("art")
    suffix = path.suffix.lower() or ""
    key = f"ws/{workspace_id}/{prefix.strip('/')}/{artifact_id}{suffix}"
    get_store().put_file(key, path, mime)
    row = {
        "id": artifact_id,
        "workspace_id": workspace_id,
        "kind": kind,
        "object_key": key,
        "mime": mime,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "produced_by_task": produced_by_task,
        "derived_from": derived_from,
        "source_url": source_url,
        "label": label,
        **_shape(path, kind),
    }
    conn.execute(insert(db.artifacts).values(**row))
    return public(row)


def get(conn: Connection, artifact_id: str) -> dict | None:
    row = conn.execute(select(db.artifacts).where(db.artifacts.c.id == artifact_id)).mappings().first()
    return dict(row) if row else None


def fetch_local(conn: Connection, artifact_id: str, dest_dir: Path) -> Path:
    row = get(conn, artifact_id)
    if not row:
        raise RuntimeError(f"没有这个文件：{artifact_id}")
    suffix = Path(row["object_key"]).suffix
    dest = dest_dir / f"{artifact_id}{suffix}"
    if not dest.is_file():
        get_store().download_to(row["object_key"], dest)
    return dest


def public(row: dict | None) -> dict | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "mime": row["mime"],
        "bytes": row["bytes"],
        "width": row.get("width"),
        "height": row.get("height"),
        "duration": row.get("duration"),
        "label": row.get("label") or "",
        "url": media_url(row["id"]),
    }
