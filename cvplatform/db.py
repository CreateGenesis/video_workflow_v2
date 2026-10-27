"""Platform database. Production and the V3 suite use PostgreSQL."""

from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

_engine: Engine | None = None


def database_url() -> str:
    return os.environ.get("CVGEN_PLATFORM_DATABASE_URL", "sqlite:///:memory:")


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, future=True, connect_args=connect_args)
        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _fk(dbapi_connection, _record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return _engine


def init_schema(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    statements = SCHEMA_SQLITE if str(engine.url).startswith("sqlite") else SCHEMA_POSTGRES
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


@contextmanager
def session():
    own = Session(get_engine(), future=True)
    try:
        yield own
        own.commit()
    except Exception:
        own.rollback()
        raise
    finally:
        own.close()


SCHEMA_SQLITE = [
    """
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      type TEXT NOT NULL,
      input TEXT NOT NULL,
      output TEXT,
      error TEXT,
      status TEXT NOT NULL,
      attempt INTEGER NOT NULL DEFAULT 0,
      max_attempts INTEGER NOT NULL DEFAULT 3,
      lease_owner TEXT,
      lease_expires_at TEXT,
      accepted_at TEXT,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      status TEXT NOT NULL,
      prompt TEXT NOT NULL DEFAULT '',
      title TEXT NOT NULL DEFAULT '',
      provider_instance TEXT NOT NULL DEFAULT '',
      model TEXT NOT NULL DEFAULT '',
      artifact_id TEXT,
      origin_task_id TEXT,
      origin_job_id TEXT,
      run_id TEXT,
      work_id TEXT,
      asset_id TEXT,
      cost_yuan TEXT NOT NULL DEFAULT '0',
      duration TEXT,
      resolution TEXT,
      accepted INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_parts (
      id TEXT PRIMARY KEY,
      product_id TEXT NOT NULL,
      part_kind TEXT NOT NULL,
      artifact_id TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_inputs (
      id TEXT PRIMARY KEY,
      product_id TEXT NOT NULL,
      input_product_id TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      name TEXT NOT NULL,
      kind TEXT NOT NULL,
      kept INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_versions (
      id TEXT PRIMARY KEY,
      asset_id TEXT NOT NULL,
      version INTEGER NOT NULL,
      lock_text TEXT NOT NULL DEFAULT '',
      accepted INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS episodes (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      workflow_version_id TEXT,
      script TEXT NOT NULL DEFAULT '',
      dialogue_mode TEXT,
      dialogue_confirmed INTEGER NOT NULL DEFAULT 0,
      aspect TEXT,
      aspect_confirmed INTEGER NOT NULL DEFAULT 0,
      mode TEXT,
      mode_confirmed INTEGER NOT NULL DEFAULT 0,
      episode_duration REAL,
      color_grade TEXT,
      color_confirmed INTEGER NOT NULL DEFAULT 0,
      subtitles TEXT,
      subtitles_confirmed INTEGER NOT NULL DEFAULT 0,
      music TEXT,
      music_confirmed INTEGER NOT NULL DEFAULT 0,
      loudness TEXT,
      loudness_confirmed INTEGER NOT NULL DEFAULT 0,
      g1 TEXT NOT NULL DEFAULT 'pending',
      published INTEGER NOT NULL DEFAULT 0,
      work_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS segments (
      id TEXT PRIMARY KEY,
      episode_id TEXT NOT NULL,
      number INTEGER NOT NULL,
      duration REAL,
      cast_json TEXT NOT NULL DEFAULT '[]',
      scene TEXT NOT NULL DEFAULT '',
      action TEXT NOT NULL DEFAULT '',
      dialogue TEXT NOT NULL DEFAULT '',
      end_state TEXT NOT NULL DEFAULT '',
      confirmed INTEGER NOT NULL DEFAULT 0,
      one_action_checked INTEGER NOT NULL DEFAULT 0,
      speakers_json TEXT NOT NULL DEFAULT '[]',
      seed TEXT,
      prompt TEXT,
      prompt_accepted INTEGER NOT NULL DEFAULT 0,
      g2 TEXT NOT NULL DEFAULT 'pending',
      g4 TEXT NOT NULL DEFAULT 'pending'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS slots (
      id TEXT PRIMARY KEY,
      episode_id TEXT NOT NULL,
      segment_id TEXT,
      kind TEXT NOT NULL,
      number INTEGER,
      asset_id TEXT,
      asset_version_id TEXT,
      product_id TEXT,
      empty INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS probe_specs (
      id TEXT PRIMARY KEY,
      segment_id TEXT NOT NULL,
      resolution TEXT NOT NULL,
      mode TEXT NOT NULL,
      duration REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS probe_results (
      id TEXT PRIMARY KEY,
      segment_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      g3 TEXT NOT NULL DEFAULT 'pending',
      superseded INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ratios (
      id TEXT PRIMARY KEY,
      episode_id TEXT NOT NULL,
      left_role TEXT NOT NULL,
      right_role TEXT NOT NULL,
      left_ratio REAL NOT NULL,
      right_ratio REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS number_maps (
      id TEXT PRIMARY KEY,
      episode_id TEXT NOT NULL,
      asset_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      number INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_instances (
      name TEXT PRIMARY KEY,
      protocol TEXT NOT NULL,
      workflow_id TEXT NOT NULL DEFAULT '',
      base_url TEXT NOT NULL DEFAULT '',
      token TEXT NOT NULL DEFAULT '',
      input_rules TEXT NOT NULL DEFAULT '{}',
      unit_price TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_versions (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      protocol TEXT NOT NULL,
      pinned_json TEXT NOT NULL DEFAULT '{}',
      published INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_cards (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      name TEXT NOT NULL,
      transport TEXT NOT NULL,
      address TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT '未验证',
      example TEXT NOT NULL DEFAULT '',
      last_error TEXT NOT NULL DEFAULT '',
      verified_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_forms (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      name TEXT NOT NULL,
      fields_json TEXT NOT NULL,
      example TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT '未验证',
      last_error TEXT NOT NULL DEFAULT '',
      verified_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_benchmarks (
      id TEXT PRIMARY KEY,
      instance TEXT NOT NULL,
      case_name TEXT NOT NULL,
      result TEXT NOT NULL,
      detail TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS characters (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      name TEXT NOT NULL,
      images_json TEXT NOT NULL,
      setting TEXT NOT NULL,
      voice_file_id TEXT NOT NULL,
      revision INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS character_refs (
      id TEXT PRIMARY KEY,
      character_id TEXT NOT NULL,
      revision INTEGER NOT NULL,
      segment_id TEXT,
      prototype_id TEXT,
      number INTEGER NOT NULL,
      images_json TEXT NOT NULL,
      image_numbers_json TEXT NOT NULL,
      voice_file_id TEXT NOT NULL,
      setting TEXT NOT NULL,
      environment_json TEXT NOT NULL,
      compressed TEXT,
      job_id TEXT,
      stale INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS uploads (
      id TEXT PRIMARY KEY,
      workspace_id TEXT NOT NULL,
      name TEXT NOT NULL,
      media_type TEXT NOT NULL,
      byte_size INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
      id TEXT PRIMARY KEY,
      episode_id TEXT NOT NULL,
      segment_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      label TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_products_prompt ON products(prompt)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status)",
]

def _postgres_statement(statement: str) -> str:
    """Keep counters as integers. Flag columns stay numeric 0/1, not PostgreSQL booleans."""
    if not statement.lstrip().startswith("CREATE TABLE"):
        return statement
    return statement.replace(" INTEGER NOT NULL DEFAULT 0", " SMALLINT NOT NULL DEFAULT 0").replace(
        " INTEGER NOT NULL DEFAULT 1", " SMALLINT NOT NULL DEFAULT 1"
    )


SCHEMA_POSTGRES = [
    _postgres_statement(statement)
    for statement in SCHEMA_SQLITE
    if not statement.startswith("CREATE INDEX")
] + [
    "CREATE INDEX IF NOT EXISTS ix_products_prompt ON products (prompt)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status)",
]
