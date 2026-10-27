"""In-process platform tests against a throwaway PostgreSQL database.

Set CVGEN_TEST_DATABASE_URL to an admin URL that can create databases, for example
postgresql://postgres@127.0.0.1:55432/postgres.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

ADMIN_URL = os.environ.get("CVGEN_TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:55432/postgres")


def _admin():
    import psycopg

    return psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=5)


def _can_connect() -> bool:
    try:
        with _admin():
            return True
    except Exception:
        return False


def _truncate(url: str) -> None:
    import psycopg

    with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        names = [row[0] for row in rows]
        if names:
            quoted = ", ".join(f'"{name}"' for name in names)
            conn.execute(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE")


@pytest.fixture(scope="session")
def pg_database():
    if not _can_connect():
        pytest.fail(f"PostgreSQL 测试库连不上：{ADMIN_URL}")
    name = f"cvgen_v3_{uuid.uuid4().hex[:8]}"
    with _admin() as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = ADMIN_URL.rpartition("/")
    url = f"{base.replace('postgresql://', 'postgresql+psycopg://')}/{name}"
    os.environ["CVGEN_PLATFORM_DATABASE_URL"] = url
    from cvplatform import db

    db.reset_engine()
    db.init_schema()
    yield url
    db.reset_engine()
    with _admin() as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture()
def client(pg_database, monkeypatch):
    monkeypatch.setenv("CVGEN_PLATFORM_DATABASE_URL", pg_database)
    _truncate(pg_database.replace("postgresql+psycopg://", "postgresql://"))
    from cvplatform import db

    db.reset_engine()
    from cvplatform.app import app

    with TestClient(app) as test:
        yield test
    db.reset_engine()
