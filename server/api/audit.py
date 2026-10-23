"""Audit: activity feed, reviewer notes for the agent, cost summaries, and a live event stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, insert, select, update

from .. import db, events
from ..auth import Principal, current_principal, need
from ..config import get_settings
from .common import number

router = APIRouter(prefix="/api", tags=["audit"])


class NoteIn(BaseModel):
    workspace_id: str
    text: str
    work_id: str | None = None
    run_id: str | None = None
    target_kind: str = ""
    target_id: str = ""


@router.get("/activity")
def activity(work_id: str = "", run_id: str = "", actor: str = "", action: str = "", before: int = 0, limit: int = 100,
             principal: Principal = Depends(need("activity:read"))) -> dict:
    query = select(db.events).order_by(db.events.c.id.desc()).limit(min(limit, 500))
    if work_id:
        query = query.where(db.events.c.work_id == work_id)
    if run_id:
        query = query.where(db.events.c.run_id == run_id)
    if actor:
        kind, _, actor_id = actor.partition(":")
        query = query.where(db.events.c.actor_kind == kind)
        if actor_id:
            query = query.where(db.events.c.actor_id == actor_id)
    if action:
        query = query.where(db.events.c.action.like(f"{action}%"))
    if before:
        query = query.where(db.events.c.id < before)
    with db.tx() as conn:
        rows = [dict(row) for row in conn.execute(query).mappings()]
    return {"items": rows, "next_before": rows[-1]["id"] if rows else None}


@router.get("/notes")
def list_notes(work_id: str = "", run_id: str = "", open_only: bool = True, all: bool = False, principal: Principal = Depends(need("notes:read"))) -> dict:
    query = select(db.review_notes).order_by(db.review_notes.c.created_at.desc()).limit(200)
    if work_id:
        query = query.where(db.review_notes.c.work_id == work_id)
    if run_id:
        query = query.where(db.review_notes.c.run_id == run_id)
    if open_only and not all:
        query = query.where(db.review_notes.c.resolved.is_(False))
    with db.tx() as conn:
        rows = conn.execute(query.add_columns(db.users.c.display_name.label("author_name")).outerjoin(
            db.users, db.users.c.id == db.review_notes.c.author_id)).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.post("/notes")
def add_note(body: NoteIn, principal: Principal = Depends(need("notes:write"))) -> dict:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="意见不能为空")
    note_id = db.new_id("note")
    with db.tx() as conn:
        conn.execute(insert(db.review_notes).values(
            id=note_id, workspace_id=body.workspace_id, work_id=body.work_id, run_id=body.run_id,
            target_kind=body.target_kind, target_id=body.target_id, author_id=principal.id, text=body.text.strip(),
        ))
        events.record(conn, principal, "note.create", workspace_id=body.workspace_id, work_id=body.work_id,
                      run_id=body.run_id, target_kind=body.target_kind or "note", target_id=body.target_id or note_id,
                      payload={"text": body.text.strip()[:200]})
        return dict(conn.execute(select(db.review_notes).where(db.review_notes.c.id == note_id)).mappings().one())


@router.post("/notes/{note_id}/resolve")
def resolve_note(note_id: str, principal: Principal = Depends(need("notes:read"))) -> dict:
    with db.tx() as conn:
        done = conn.execute(update(db.review_notes).where(db.review_notes.c.id == note_id).values(
            resolved=True, resolved_by=f"{principal.kind}:{principal.name}", resolved_at=db.now())).rowcount
        if not done:
            raise HTTPException(status_code=404, detail="没有这条意见")
        note = dict(conn.execute(select(db.review_notes).where(db.review_notes.c.id == note_id)).mappings().one())
        events.record(conn, principal, "note.resolve", workspace_id=note["workspace_id"], work_id=note["work_id"],
                      run_id=note["run_id"], target_kind="note", target_id=note_id)
        return note


@router.get("/costs")
def costs(group: str = "day", workspace_id: str = "", days: int = 30, principal: Principal = Depends(need("costs:read"))) -> dict:
    columns = {
        "day": func.date_trunc("day", db.cost_ledger.c.created_at),
        "work": db.cost_ledger.c.work_id,
        "run": db.cost_ledger.c.run_id,
        "provider": db.cost_ledger.c.provider_instance,
        "actor": func.concat(db.cost_ledger.c.actor_kind, ":", db.cost_ledger.c.actor_id),
    }
    if group not in columns:
        raise HTTPException(status_code=400, detail=f"group 只能是 {', '.join(columns)}")
    key = columns[group].label("key")
    query = (select(key, func.sum(db.cost_ledger.c.amount_yuan).label("yuan"), func.count().label("entries"))
             .where(db.cost_ledger.c.created_at >= func.now() - func.make_interval(0, 0, 0, max(1, min(days, 366))))
             .group_by(key).order_by(key.desc()))
    scope = workspace_id or principal.workspace_id
    if scope:
        query = query.where(db.cost_ledger.c.workspace_id == scope)
    if principal.kind == "device":
        query = query.where(db.cost_ledger.c.actor_kind == "device", db.cost_ledger.c.actor_id == principal.id)
    with db.tx() as conn:
        rows = conn.execute(query).all()
    items = [{"key": row.key, "yuan": number(row.yuan), "entries": row.entries} for row in rows]
    return {"group": group, "items": items, "total_yuan": round(sum(item["yuan"] or 0 for item in items), 4)}


@router.get("/events/stream")
async def stream(principal: Principal = Depends(current_principal)):
    """Server-sent events: one `change` event per NOTIFY, plus a heartbeat every 15 s. Clients refetch."""
    import psycopg

    url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")

    async def generate():
        conn = await psycopg.AsyncConnection.connect(url, autocommit=True)
        try:
            await conn.execute("LISTEN cvgen_events")
            yield "retry: 3000\n\n"
            while True:
                received = False
                try:
                    async for notice in conn.notifies(timeout=15.0, stop_after=50):
                        received = True
                        yield f"event: change\ndata: {json.dumps({'ref': notice.payload})}\n\n"
                except asyncio.CancelledError:
                    raise
                if not received:
                    yield ": keepalive\n\n"
        finally:
            await conn.close()

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
