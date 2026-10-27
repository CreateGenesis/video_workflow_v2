"""The two processes answer different health payloads."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from agent.app import app as agent_app
from cvplatform.app import app as platform_app


def test_claim_once_routes_only_after_a_row_is_claimed(monkeypatch, tmp_path):
    monkeypatch.setenv("CVGEN_PLATFORM_DATABASE_URL", "sqlite:///" + str(tmp_path / "jobs.db"))
    from cvplatform import db

    db.reset_engine()
    with TestClient(platform_app) as platform, TestClient(agent_app) as agent:
        monkeypatch.setenv("CVGEN_PLATFORM_URL", "http://platform.test")

        def handler(request):
            if request.url.path == "/api/jobs/claim":
                return httpx.Response(200, json={"claimed": True, "job": {"id": "job-1", "type": "write_prompt"}})
            return httpx.Response(404, json={"detail": "missing"})

        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Client(transport=transport).post(url, **kwargs))
        claimed = agent.post("/api/claim-once", params={"owner": "agent-1"})
        assert claimed.status_code == 200
        body = claimed.json()
        assert body["model_called"] is True
        assert body["member"] == "prompt-only"

        def empty(request):
            return httpx.Response(200, json={"claimed": False, "job": None})

        empty_transport = httpx.MockTransport(empty)
        monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Client(transport=empty_transport).post(url, **kwargs))
        missed = agent.post("/api/claim-once", params={"owner": "agent-1"})
        assert missed.json()["model_called"] is False
        assert missed.json()["member"] is None
        assert platform.get("/api/health").json()["process"] == "platform"
    db.reset_engine()


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
