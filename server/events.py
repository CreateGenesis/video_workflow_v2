"""Append-only audit log. Every write that changes what people or agents see goes through here."""

from __future__ import annotations

from sqlalchemy import insert
from sqlalchemy.engine import Connection

from . import db


def record(
    conn: Connection,
    principal,
    action: str,
    *,
    workspace_id: str | None = None,
    work_id: str | None = None,
    run_id: str | None = None,
    target_kind: str = "",
    target_id: str = "",
    payload: dict | None = None,
) -> None:
    conn.execute(insert(db.events).values(
        actor_kind=principal.kind,
        actor_id=principal.id,
        actor_name=principal.name,
        workspace_id=workspace_id,
        work_id=work_id,
        run_id=run_id,
        action=action,
        target_kind=target_kind,
        target_id=target_id or "",
        payload=payload or {},
    ))
    db.notify(conn, "cvgen_events", run_id or work_id or "")
