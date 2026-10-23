"""Test harness: a throwaway PostgreSQL database per session, truncated before every test.

Set CVGEN_TEST_DATABASE_URL to an admin URL of a server you can create databases on, e.g.
postgresql://postgres@127.0.0.1:55432/postgres (default). Tests that need it are skipped if
the server cannot be reached.
"""

from __future__ import annotations

import os
import uuid

import pytest

ADMIN_URL = os.environ.get("CVGEN_TEST_DATABASE_URL", "postgresql://postgres@127.0.0.1:55432/postgres")


def _can_connect() -> bool:
    try:
        import psycopg

        with psycopg.connect(ADMIN_URL, connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database(tmp_path_factory):
    if not _can_connect():
        pytest.skip("PostgreSQL 测试库连不上（设置 CVGEN_TEST_DATABASE_URL）")
    import psycopg

    name = f"cvgen_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = ADMIN_URL.rpartition("/")
    os.environ["CVGEN_DATABASE_URL"] = f"{base.replace('postgresql://', 'postgresql+psycopg://')}/{name}"
    os.environ["CVGEN_DATA"] = str(tmp_path_factory.mktemp("cvgen-data"))
    os.environ["CVGEN_SECRET_KEY"] = "test-secret-key-for-cvgen"
    os.environ["CVGEN_PUBLIC_BASE"] = "http://testserver"
    os.environ.pop("CVGEN_S3_ENDPOINT", None)
    os.environ.pop("RUSTFS_ENDPOINT", None)
    os.environ.pop("AUTODL_API_TOKEN", None)
    from server import config, db, storage

    config.reset_settings()
    db.reset_engine()
    storage.reset_store()
    from server.manage import migrate

    migrate()
    yield name
    db.reset_engine()
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture()
def fresh(database, monkeypatch):
    """Empty tables, default workspace, system pools."""
    from sqlalchemy import text

    from server import db
    from server.app import bootstrap
    from server.auth import limiter
    from server.providers import mock

    monkeypatch.setenv("CVGEN_SEED_MOCK", "0")
    with db.tx() as conn:
        tables = [row[0] for row in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"))]
        conn.execute(text("TRUNCATE " + ", ".join(f'"{name}"' for name in tables) + " RESTART IDENTITY CASCADE"))
    mock.reset()
    limiter._hits.clear()
    bootstrap()
    with db.tx() as conn:
        workspace_id = conn.execute(db.workspaces.select()).first().id
    return {"workspace_id": workspace_id}


@pytest.fixture()
def client(fresh):
    from fastapi.testclient import TestClient

    from server.app import app

    with TestClient(app) as test_client:
        yield test_client


class Api:
    """A signed-in browser-like client: cookie session plus the CSRF header the web sends."""

    def __init__(self, test_client, headers: dict | None = None):
        self.client = test_client
        self.headers = headers or {}

    def request(self, method: str, path: str, expect: int | None = 200, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        response = self.client.request(method, path, headers=headers, **kwargs)
        if expect is not None:
            assert response.status_code == expect, f"{method} {path} -> {response.status_code}: {response.text}"
        return response

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs).json()

    def post(self, path: str, json=None, **kwargs):
        return self.request("POST", path, json=json, **kwargs).json()

    def patch(self, path: str, json=None, **kwargs):
        return self.request("PATCH", path, json=json, **kwargs).json()

    def put(self, path: str, json=None, **kwargs):
        return self.request("PUT", path, json=json, **kwargs).json()

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs).json()


@pytest.fixture()
def admin(client):
    response = client.post("/api/auth/setup", json={"username": "admin", "password": "adminpass1"})
    assert response.status_code == 200, response.text
    return Api(client, {"X-CVGEN-CSRF": "1"})


def make_user(admin: Api, username: str, role: str) -> Api:
    from fastapi.testclient import TestClient

    from server.app import app

    admin.post("/api/admin/users", {"username": username, "password": f"{username}pass1", "role": role})
    other = TestClient(app)
    response = other.post("/api/auth/login", json={"username": username, "password": f"{username}pass1"})
    assert response.status_code == 200, response.text
    return Api(other, {"X-CVGEN-CSRF": "1"})


def make_device(owner: Api, name: str = "agent") -> Api:
    start = owner.client.post("/api/device/start", json={"name": name, "client_version": "0.2.0"}).json()
    owner.post(f"/api/devices/code/{start['user_code']}/approve")
    token = owner.client.post("/api/device/poll", json={"device_id": start["device_id"],
                                                        "poll_secret": start["poll_secret"]}).json()["token"]
    from fastapi.testclient import TestClient

    from server.app import app

    return Api(TestClient(app), {"Authorization": f"Bearer {token}"})


@pytest.fixture()
def agent(admin):
    return make_device(admin)


@pytest.fixture()
def mock_providers(fresh):
    """Mock instances for every kind, including the names the example workflows use."""
    from server import db
    from server.auth import SYSTEM
    from server.providers import instances

    with db.tx() as conn:
        instances.ensure_pool(conn, "llm", 4)
        instances.ensure_pool(conn, "image-api", 4)
        instances.ensure_pool(conn, "gpu", 1)
        instances.ensure_pool(conn, "autodl-h3", 1)
        pricing = {"token_in": 0.000004, "token_out": 0.00002, "image": 0.2, "video_second": 0.5}
        for name, kind, pool, extra in [
            ("llm.default", "llm", "llm", {}),
            ("image.default", "image", "image-api", {}),
            ("video.default", "video", "gpu", {}),
            ("video.comfy-gpu1", "video", "gpu", {"group_name": "video.comfy"}),
            ("video.autodl-h3", "video", "autodl-h3", {"retry_safe": False, "max_attempts": 1}),
            ("tts.default", "tts", "local", {}),
            ("music.default", "music", "local", {}),
        ]:
            instances.save(conn, SYSTEM, name, {"kind": kind, "protocol": "mock", "pool": pool, "pricing": pricing,
                                                **extra})
    return True


def run_worker(limit: int = 500) -> int:
    from server.engine.worker import Worker

    return Worker("test-worker").run_until_idle(limit)
