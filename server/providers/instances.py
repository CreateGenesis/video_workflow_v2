"""Provider instances and resource pools, stored in PostgreSQL. Secrets are encrypted at rest."""

from __future__ import annotations

import os
import re

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from .. import db, events
from ..config import ROOT
from ..security import decrypt_secret, encrypt_secret, mask
from . import KINDS, protocol_kinds
from .base import Instance

NAME_RE = re.compile(r"^(llm|image|video|tts|music)\.[a-z0-9][a-z0-9-]{0,39}$")
POOL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
SYSTEM_POOLS = {"ffmpeg": max(1, (os.cpu_count() or 2) // 2), "local": 4}
GATE_POOL = "gate"
FIELDS = ("kind", "protocol", "group_name", "base_url", "model", "pool", "capabilities", "retry_safe",
          "max_attempts", "timeout_seconds", "pricing", "options", "enabled")


def to_instance(row) -> Instance:
    return Instance(
        name=row.name, kind=row.kind, protocol=row.protocol, base_url=row.base_url,
        secret=decrypt_secret(row.secret_enc), model=row.model, pool=row.pool,
        capabilities=dict(row.capabilities or {}), retry_safe=row.retry_safe, max_attempts=row.max_attempts,
        timeout_seconds=row.timeout_seconds, pricing=dict(row.pricing or {}), options=dict(row.options or {}),
    )


def public(row) -> dict:
    data = dict(row._mapping)
    secret = decrypt_secret(data.pop("secret_enc", ""))
    data["secret"] = mask(secret)
    data["configured"] = bool(secret) or data["protocol"] in {"mock", "comfyui"}
    return data


def list_instances(conn: Connection) -> list:
    return list(conn.execute(select(db.provider_instances).order_by(db.provider_instances.c.kind, db.provider_instances.c.name)))


def get_row(conn: Connection, name: str):
    return conn.execute(select(db.provider_instances).where(db.provider_instances.c.name == name)).first()


def resolve(conn: Connection, ref: str, kind: str | None = None) -> list[Instance]:
    """A workflow names an instance or a group (for example video.comfy = gpu1 + gpu2)."""
    rows = conn.execute(
        select(db.provider_instances).where(
            db.provider_instances.c.enabled.is_(True),
            (db.provider_instances.c.name == ref) | (db.provider_instances.c.group_name == ref),
        ).order_by(db.provider_instances.c.name)
    ).all()
    if kind:
        rows = [row for row in rows if row.kind == kind]
    return [to_instance(row) for row in rows]


def default_for(conn: Connection, kind: str) -> list[Instance]:
    found = resolve(conn, f"{kind}.default", kind)
    if found:
        return found
    rows = conn.execute(select(db.provider_instances).where(
        db.provider_instances.c.enabled.is_(True), db.provider_instances.c.kind == kind,
    ).order_by(db.provider_instances.c.name)).all()
    return [to_instance(rows[0])] if rows else []


def save(conn: Connection, principal, name: str, fields: dict, secret: str | None = None, clear_secret: bool = False) -> dict:
    if not NAME_RE.match(name or ""):
        raise ValueError("实例名要写成 能力.名称，例如 video.comfy-gpu1、llm.default")
    existing = get_row(conn, name)
    values = {key: fields[key] for key in FIELDS if key in fields and fields[key] is not None}
    kind = values.get("kind") or (existing.kind if existing else name.split(".", 1)[0])
    if kind not in KINDS or kind != name.split(".", 1)[0]:
        raise ValueError("实例名前缀必须和能力一致")
    values["kind"] = kind
    protocol = values.get("protocol") or (existing.protocol if existing else "")
    if kind not in protocol_kinds(protocol):
        raise ValueError(f"协议 {protocol} 不能用于 {kind}")
    if values.get("group_name") and not NAME_RE.match(values["group_name"]):
        raise ValueError("实例组名的写法和实例名一样，例如 video.comfy")
    pool = values.get("pool") or (existing.pool if existing else "")
    if not pool:
        pool = {"llm": "llm", "image": "image-api"}.get(kind, name.split(".", 1)[1])
        values["pool"] = pool
    if not POOL_RE.match(pool) or pool == GATE_POOL:
        raise ValueError("资源池名只能用小写字母、数字和 -")
    ensure_pool(conn, pool)
    if secret:
        values["secret_enc"] = encrypt_secret(secret)
    elif clear_secret:
        values["secret_enc"] = ""
    values["updated_at"] = db.now()
    if existing:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == name).values(**values))
    else:
        values.setdefault("retry_safe", protocol not in {"autodl-h3", "autodl-indextts"})
        values.setdefault("max_attempts", 1 if not values["retry_safe"] else 3)
        conn.execute(insert(db.provider_instances).values(name=name, **values))
    events.record(conn, principal, "provider.save", target_kind="provider", target_id=name,
                  payload={key: value for key, value in values.items() if key not in {"secret_enc", "updated_at"}}
                  | {"secret_changed": bool(secret) or clear_secret})
    return public(get_row(conn, name))


def remove(conn: Connection, principal, name: str) -> None:
    conn.execute(delete(db.provider_instances).where(db.provider_instances.c.name == name))
    events.record(conn, principal, "provider.delete", target_kind="provider", target_id=name)


def ensure_pool(conn: Connection, name: str, concurrency: int | None = None) -> None:
    stmt = pg_insert(db.pools).values(name=name, concurrency=concurrency or 1).on_conflict_do_nothing()
    conn.execute(stmt)
    if concurrency is not None:
        conn.execute(update(db.pools).where(db.pools.c.name == name).values(concurrency=concurrency))
    sync_slots(conn, name)


def set_pool(conn: Connection, principal, name: str, *, concurrency: int | None = None,
             rate_per_minute: int | None = None, paused: bool | None = None, note: str | None = None) -> dict:
    if not POOL_RE.match(name) or name == GATE_POOL:
        raise ValueError("资源池名只能用小写字母、数字和 -")
    ensure_pool(conn, name)
    values = {}
    if concurrency is not None:
        if not 0 <= concurrency <= 64:
            raise ValueError("并发数在 0 到 64 之间")
        values["concurrency"] = concurrency
    if rate_per_minute is not None:
        values["rate_per_minute"] = rate_per_minute or None
    if paused is not None:
        values["paused"] = paused
    if note is not None:
        values["note"] = note
    if values:
        conn.execute(update(db.pools).where(db.pools.c.name == name).values(**values))
    sync_slots(conn, name)
    events.record(conn, principal, "pool.update", target_kind="pool", target_id=name, payload=values)
    db.notify(conn, "cvgen_tasks", name)
    return dict(conn.execute(select(db.pools).where(db.pools.c.name == name)).mappings().one())


def sync_slots(conn: Connection, pool: str) -> None:
    """Slot rows = concurrency. Busy slots above the limit stay until their task finishes."""
    concurrency = conn.execute(select(db.pools.c.concurrency).where(db.pools.c.name == pool)).scalar_one()
    count = conn.execute(select(func.count()).select_from(db.pool_slots).where(db.pool_slots.c.pool == pool)).scalar_one()
    for slot in range(count, concurrency):
        conn.execute(pg_insert(db.pool_slots).values(pool=pool, slot=slot).on_conflict_do_nothing())
    conn.execute(delete(db.pool_slots).where(
        db.pool_slots.c.pool == pool, db.pool_slots.c.slot >= concurrency, db.pool_slots.c.task_id.is_(None),
    ))


def pools_overview(conn: Connection, cache: dict | None = None) -> list[dict]:
    cache = {} if cache is None else cache
    rows = conn.execute(select(db.pools).order_by(db.pools.c.name)).mappings().all()
    result = []
    for row in rows:
        busy = conn.execute(select(func.count()).select_from(db.pool_slots).where(
            db.pool_slots.c.pool == row["name"], db.pool_slots.c.task_id.isnot(None),
        )).scalar_one()
        waiting = conn.execute(select(func.count()).select_from(db.tasks).where(
            db.tasks.c.pool == row["name"], db.tasks.c.status == "ready",
        )).scalar_one()
        from ..engine.eta import pool_eta_seconds

        result.append({
            **dict(row), "busy": busy, "ready": waiting,
            "eta_seconds": pool_eta_seconds(conn, row["name"], cache),
        })
    return result


def _file_env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.is_file():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def seed(conn: Connection, principal) -> list[str]:
    """First start: create system pools, and provider instances from the legacy environment variables."""
    for pool, concurrency in SYSTEM_POOLS.items():
        ensure_pool(conn, pool, None if conn.execute(select(db.pools.c.name).where(db.pools.c.name == pool)).first() else concurrency)
    if conn.execute(select(func.count()).select_from(db.provider_instances)).scalar_one():
        return []
    env = {**_file_env(), **os.environ}
    created = []
    if env.get("CVGEN_SEED_MOCK") == "1":
        ensure_pool(conn, "mock-gpu", 1)
        for kind in KINDS:
            pool = {"llm": "llm", "image": "image-api", "video": "mock-gpu"}.get(kind, "local")
            ensure_pool(conn, pool, {"llm": 8, "image-api": 4}.get(pool, 1 if pool == "mock-gpu" else 4))
            save(conn, principal, f"{kind}.default", {
                "kind": kind, "protocol": "mock", "pool": pool,
                "pricing": {"token_in": 0.000004, "token_out": 0.00002, "image": 0.2, "video_second": 0.5},
            })
            created.append(f"{kind}.default")
        ensure_pool(conn, "mock-paid", 1)
        save(conn, principal, "video.comfy-gpu1", {"kind": "video", "protocol": "mock", "pool": "mock-gpu",
                                                   "group_name": "video.comfy", "pricing": {"gpu_second": 0.001}})
        save(conn, principal, "video.autodl-h3", {"kind": "video", "protocol": "mock", "pool": "mock-paid",
                                                  "retry_safe": False, "max_attempts": 1,
                                                  "pricing": {"video_second": 0.5}})
        return created + ["video.comfy-gpu1", "video.autodl-h3"]
    token = env.get("AUTODL_API_TOKEN", "")
    if token:
        ensure_pool(conn, "autodl-h3", 2)
        base = env.get("AUTODL_API_BASE", "https://www.autodl.art")
        save(conn, principal, "video.autodl-h3", {
            "kind": "video", "protocol": "autodl-h3", "base_url": base, "pool": "autodl-h3",
            "model": env.get("H3_WORKFLOW_ID", "minimax_h3_zm_u24"), "retry_safe": False, "max_attempts": 1,
            "timeout_seconds": 3600, "pricing": {"video_second": 0.5},
        }, secret=token)
        save(conn, principal, "tts.autodl-indextts", {
            "kind": "tts", "protocol": "autodl-indextts", "base_url": base, "pool": "autodl-h3",
            "model": "indextts2-v1", "retry_safe": False, "max_attempts": 1, "timeout_seconds": 1800,
        }, secret=token)
        created += ["video.autodl-h3", "tts.autodl-indextts"]
    for kind, protocol, prefix in (("image", "openai-images", "CVGEN_IMAGE"), ("music", "openai-audio", "CVGEN_MUSIC")):
        if env.get(f"{prefix}_BASE") and env.get(f"{prefix}_KEY"):
            pool = "image-api" if kind == "image" else "local"
            ensure_pool(conn, pool, 4)
            save(conn, principal, f"{kind}.default", {
                "kind": kind, "protocol": protocol, "base_url": env[f"{prefix}_BASE"],
                "model": env.get(f"{prefix}_WORKFLOW", ""), "pool": pool,
            }, secret=env[f"{prefix}_KEY"])
            created.append(f"{kind}.default")
    return created
