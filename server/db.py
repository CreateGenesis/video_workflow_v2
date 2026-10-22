"""PostgreSQL schema and connection helpers. Alembic migrations are generated from this metadata."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterator

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.types import DateTime

from .config import get_settings

metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})


def _ts(name: str, nullable: bool = True, default: bool = False) -> Column:
    if default:
        return Column(name, DateTime(timezone=True), nullable=False, server_default=func.now())
    return Column(name, DateTime(timezone=True), nullable=nullable)


def _json(name: str, default: str = "'{}'::jsonb") -> Column:
    return Column(name, JSONB, nullable=False, server_default=text(default))


users = Table(
    "users", metadata,
    Column("id", Text, primary_key=True),
    Column("username", Text, nullable=False, unique=True),
    Column("display_name", Text, nullable=False, server_default=""),
    Column("role", Text, nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("disabled", Boolean, nullable=False, server_default=text("false")),
    _ts("created_at", default=True),
)

sessions = Table(
    "sessions", metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    _ts("created_at", default=True),
    _ts("expires_at", nullable=False),
    _ts("last_seen_at"),
)

workspaces = Table(
    "workspaces", metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
    Column("created_by", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
)

devices = Table(
    "devices", metadata,
    Column("id", Text, primary_key=True),
    Column("user_id", Text, ForeignKey("users.id", ondelete="SET NULL")),
    Column("name", Text, nullable=False, server_default=""),
    Column("status", Text, nullable=False),
    Column("user_code", Text, nullable=False, unique=True),
    Column("poll_secret_hash", Text, nullable=False),
    Column("token_hash", Text, unique=True),
    Column("token_claimed", Boolean, nullable=False, server_default=text("false")),
    Column("daily_budget_yuan", Numeric(12, 2)),
    Column("client_version", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    _ts("expires_at", nullable=False),
    _ts("approved_at"),
    _ts("last_seen_at"),
)

api_keys = Table(
    "api_keys", metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("owner_user_id", Text, ForeignKey("users.id", ondelete="SET NULL")),
    Column("workspace_id", Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("scopes", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("prefix", Text, nullable=False),
    Column("key_hash", Text, nullable=False, unique=True),
    Column("rate_per_minute", Integer, nullable=False, server_default=text("60")),
    Column("monthly_budget_yuan", Numeric(12, 2)),
    _ts("created_at", default=True),
    _ts("revoked_at"),
    _ts("last_used_at"),
)

artifacts = Table(
    "artifacts", metadata,
    Column("id", Text, primary_key=True),
    Column("workspace_id", Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("object_key", Text, nullable=False, unique=True),
    Column("mime", Text, nullable=False, server_default="application/octet-stream"),
    Column("bytes", BigInteger, nullable=False, server_default=text("0")),
    Column("sha256", Text, nullable=False, server_default=""),
    Column("width", Integer),
    Column("height", Integer),
    Column("duration", Float),
    Column("produced_by_task", Text),
    Column("derived_from", Text),
    Column("source_url", Text, nullable=False, server_default=""),
    Column("label", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
)

assets = Table(
    "assets", metadata,
    Column("id", Text, primary_key=True),
    Column("workspace_id", Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False, server_default=""),
    Column("archived", Boolean, nullable=False, server_default=text("false")),
    Column("created_by", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    UniqueConstraint("workspace_id", "name", name="uq_assets_workspace_name"),
)

asset_versions = Table(
    "asset_versions", metadata,
    Column("asset_id", Text, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("data", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("artifact_id", Text, ForeignKey("artifacts.id", ondelete="SET NULL")),
    Column("note", Text, nullable=False, server_default=""),
    Column("created_by", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    PrimaryKeyConstraint("asset_id", "version", name="pk_asset_versions"),
)

works = Table(
    "works", metadata,
    Column("id", Text, primary_key=True),
    Column("workspace_id", Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("title", Text, nullable=False),
    Column("kind", Text, nullable=False, server_default=""),
    Column("brief", Text, nullable=False, server_default=""),
    Column("origin", Text, nullable=False, server_default="explore"),
    Column("run_id", Text),
    Column("created_by", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    _ts("archived_at"),
)

entities = Table(
    "entities", metadata,
    Column("id", Text, primary_key=True),
    Column("work_id", Text, ForeignKey("works.id", ondelete="CASCADE"), nullable=False),
    Column("type", Text, nullable=False),
    Column("data", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("artifact_id", Text, ForeignKey("artifacts.id", ondelete="SET NULL")),
    Column("position", JSONB),
    Column("ord", Integer, nullable=False, server_default=text("0")),
    Column("created_by", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    _ts("updated_at", default=True),
    _ts("deleted_at"),
    Index("ix_entities_work_type", "work_id", "type"),
)

links = Table(
    "links", metadata,
    Column("id", Text, primary_key=True),
    Column("work_id", Text, ForeignKey("works.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("source_id", Text, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
    Column("target_kind", Text, nullable=False, server_default="entity"),
    Column("target_id", Text, nullable=False),
    Column("target_version", Integer),
    Column("note", Text, nullable=False, server_default=""),
    Column("ord", Integer, nullable=False, server_default=text("0")),
    Column("created_by", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    _ts("deleted_at"),
    Index("ix_links_source", "source_id", "name"),
    Index("ix_links_target", "target_id"),
    Index(
        "uq_links_live",
        "work_id", "name", "source_id", "target_kind", "target_id", text("coalesce(target_version, 0)"),
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    ),
)

workflows = Table(
    "workflows", metadata,
    Column("id", Text, primary_key=True),
    Column("workspace_id", Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("archived", Boolean, nullable=False, server_default=text("false")),
    Column("created_by", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    UniqueConstraint("workspace_id", "name", name="uq_workflows_workspace_name"),
)

workflow_versions = Table(
    "workflow_versions", metadata,
    Column("workflow_id", Text, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("spec", JSONB, nullable=False),
    Column("status", Text, nullable=False, server_default="draft"),
    Column("source_work_id", Text),
    _json("fixtures"),
    Column("validation", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("notes", Text, nullable=False, server_default=""),
    Column("created_by", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    _ts("updated_at", default=True),
    Column("published_by", Text),
    _ts("published_at"),
    PrimaryKeyConstraint("workflow_id", "version", name="pk_workflow_versions"),
)

batches = Table(
    "batches", metadata,
    Column("id", Text, primary_key=True),
    Column("workspace_id", Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("workflow_id", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("size", Integer, nullable=False),
    Column("created_by_kind", Text, nullable=False),
    Column("created_by_id", Text, nullable=False),
    _ts("created_at", default=True),
)

runs = Table(
    "runs", metadata,
    Column("id", Text, primary_key=True),
    Column("workspace_id", Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("workflow_id", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("batch_id", Text),
    Column("mode", Text, nullable=False, server_default="production"),
    Column("inputs", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("status", Text, nullable=False, server_default="running"),
    Column("priority", Integer, nullable=False, server_default=text("0")),
    Column("work_id", Text, ForeignKey("works.id", ondelete="SET NULL")),
    Column("outputs", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("error", JSONB),
    Column("cost_estimate", Numeric(12, 4), nullable=False, server_default=text("0")),
    Column("cost_actual", Numeric(12, 4), nullable=False, server_default=text("0")),
    Column("created_by_kind", Text, nullable=False),
    Column("created_by_id", Text, nullable=False),
    Column("idempotency_key", Text),
    Column("callback_url", Text, nullable=False, server_default=""),
    Column("seq", BigInteger, nullable=False, server_default=text("0")),
    _ts("created_at", default=True),
    _ts("started_at"),
    _ts("finished_at"),
    Index(
        "uq_runs_idempotency",
        "created_by_kind", "created_by_id", "idempotency_key",
        unique=True,
        postgresql_where=text("idempotency_key IS NOT NULL"),
    ),
    Index("ix_runs_status", "status"),
)

pools = Table(
    "pools", metadata,
    Column("name", Text, primary_key=True),
    Column("concurrency", Integer, nullable=False, server_default=text("1")),
    Column("rate_per_minute", Integer),
    Column("paused", Boolean, nullable=False, server_default=text("false")),
    Column("note", Text, nullable=False, server_default=""),
)

pool_slots = Table(
    "pool_slots", metadata,
    Column("pool", Text, ForeignKey("pools.name", ondelete="CASCADE"), nullable=False),
    Column("slot", Integer, nullable=False),
    Column("task_id", Text),
    _ts("leased_until"),
    PrimaryKeyConstraint("pool", "slot", name="pk_pool_slots"),
)

provider_instances = Table(
    "provider_instances", metadata,
    Column("name", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("protocol", Text, nullable=False),
    Column("group_name", Text),
    Column("base_url", Text, nullable=False, server_default=""),
    Column("secret_enc", Text, nullable=False, server_default=""),
    Column("model", Text, nullable=False, server_default=""),
    Column("pool", Text, ForeignKey("pools.name"), nullable=False),
    Column("capabilities", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("retry_safe", Boolean, nullable=False, server_default=text("true")),
    Column("max_attempts", Integer, nullable=False, server_default=text("3")),
    Column("timeout_seconds", Integer, nullable=False, server_default=text("1800")),
    Column("pricing", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("options", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("enabled", Boolean, nullable=False, server_default=text("true")),
    Column("health", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    _ts("updated_at", default=True),
)

tasks = Table(
    "tasks", metadata,
    Column("id", Text, primary_key=True),
    Column("workspace_id", Text, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
    Column("run_id", Text, ForeignKey("runs.id", ondelete="CASCADE")),
    Column("work_id", Text, ForeignKey("works.id", ondelete="SET NULL")),
    Column("node_id", Text),
    Column("item_key", Text, nullable=False, server_default=""),
    Column("item_index", Integer, nullable=False, server_default=text("0")),
    Column("kind", Text, nullable=False),
    Column("provider_instance", Text),
    Column("pool", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("priority", Integer, nullable=False, server_default=text("0")),
    Column("sort_key", Text, nullable=False, server_default=""),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("max_attempts", Integer, nullable=False, server_default=text("1")),
    Column("backoff_seconds", Integer, nullable=False, server_default=text("30")),
    Column("timeout_seconds", Integer, nullable=False, server_default=text("1800")),
    Column("lease_owner", Text),
    _ts("lease_expires_at"),
    Column("cancel_requested", Boolean, nullable=False, server_default=text("false")),
    Column("provider_ref", JSONB),
    Column("input", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("output", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("error", JSONB),
    Column("attention", Text, nullable=False, server_default=""),
    Column("progress", Float, nullable=False, server_default=text("0")),
    Column("superseded_by", Text),
    Column("created_by_kind", Text, nullable=False),
    Column("created_by_id", Text, nullable=False),
    _ts("created_at", default=True),
    _ts("ready_at"),
    _ts("started_at"),
    _ts("submitted_at"),
    _ts("finished_at"),
    Index("ix_tasks_claim", "pool", "status", "priority"),
    Index("ix_tasks_run", "run_id", "node_id"),
    Index("ix_tasks_work", "work_id"),
)

task_deps = Table(
    "task_deps", metadata,
    Column("task_id", Text, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
    Column("depends_on", Text, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
    PrimaryKeyConstraint("task_id", "depends_on", name="pk_task_deps"),
    Index("ix_task_deps_depends_on", "depends_on"),
)

cost_ledger = Table(
    "cost_ledger", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("workspace_id", Text, nullable=False),
    Column("task_id", Text),
    Column("run_id", Text),
    Column("work_id", Text),
    Column("provider_instance", Text, nullable=False, server_default=""),
    Column("unit", Text, nullable=False),
    Column("quantity", Numeric(14, 4), nullable=False),
    Column("unit_price", Numeric(14, 6), nullable=False),
    Column("amount_yuan", Numeric(14, 4), nullable=False),
    Column("estimated", Boolean, nullable=False, server_default=text("false")),
    Column("actor_kind", Text, nullable=False, server_default=""),
    Column("actor_id", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
    Index("ix_cost_ledger_run", "run_id"),
    Index("ix_cost_ledger_actor", "actor_kind", "actor_id", "created_at"),
)

events = Table(
    "events", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    _ts("ts", default=True),
    Column("actor_kind", Text, nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("actor_name", Text, nullable=False, server_default=""),
    Column("workspace_id", Text),
    Column("work_id", Text),
    Column("run_id", Text),
    Column("action", Text, nullable=False),
    Column("target_kind", Text, nullable=False, server_default=""),
    Column("target_id", Text, nullable=False, server_default=""),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Index("ix_events_ts", "ts"),
    Index("ix_events_work", "work_id", "ts"),
    Index("ix_events_run", "run_id", "ts"),
)

review_notes = Table(
    "review_notes", metadata,
    Column("id", Text, primary_key=True),
    Column("workspace_id", Text, nullable=False),
    Column("work_id", Text),
    Column("run_id", Text),
    Column("target_kind", Text, nullable=False, server_default=""),
    Column("target_id", Text, nullable=False, server_default=""),
    Column("author_id", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("resolved", Boolean, nullable=False, server_default=text("false")),
    Column("resolved_by", Text),
    _ts("created_at", default=True),
    _ts("resolved_at"),
)

webhook_deliveries = Table(
    "webhook_deliveries", metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("run_id", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("event", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("status", Text, nullable=False, server_default="pending"),
    _ts("next_attempt_at", default=True),
    Column("last_error", Text, nullable=False, server_default=""),
    _ts("created_at", default=True),
)

llm_cache = Table(
    "llm_cache", metadata,
    Column("key", Text, primary_key=True),
    Column("response", JSONB, nullable=False),
    _ts("created_at", default=True),
)

settings_table = Table(
    "settings", metadata,
    Column("key", Text, primary_key=True),
    Column("value", JSONB, nullable=False),
    _ts("updated_at", default=True),
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        future=True,
    )


def reset_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()


@contextmanager
def tx() -> Iterator[Connection]:
    """One transaction. Commit on success, roll back on any exception."""
    with get_engine().begin() as conn:
        yield conn


def notify(conn: Connection, channel: str, payload: str = "") -> None:
    conn.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": channel, "payload": payload})


def get_setting(conn: Connection, key: str, default=None):
    row = conn.execute(settings_table.select().where(settings_table.c.key == key)).first()
    return row.value if row else default


def set_setting(conn: Connection, key: str, value) -> None:
    from sqlalchemy.dialects.postgresql import insert

    stmt = insert(settings_table).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value, "updated_at": func.now()})
    conn.execute(stmt)
