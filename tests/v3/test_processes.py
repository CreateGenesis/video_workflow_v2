"""The two processes answer different health payloads."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent.app import app as agent_app
from cvplatform.app import app as platform_app


def test_health_distinguishes_processes(monkeypatch, tmp_path):
    monkeypatch.setenv("CVGEN_PLATFORM_DATABASE_URL", "sqlite:///" + str(tmp_path / "p.db"))
    from cvplatform import db

    db.reset_engine()
    with TestClient(platform_app) as platform, TestClient(agent_app) as agent:
        left = platform.get("/api/health").json()
        right = agent.get("/api/health").json()
    assert left["process"] == "platform"
    assert right["process"] == "agent"
    assert left["service"] != right["service"]
    db.reset_engine()
