"""Jobs claim protocol through the platform API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cvplatform.db import session
from cvplatform.jobs import claim, complete, enqueue, inspect


def test_two_claimers_cannot_take_the_same_row(client):
    created = client.post("/api/jobs", json={"workspace_id": "ws", "type": "write_prompt", "input": {"segment": 1}}).json()
    first = client.post("/api/jobs/claim", params={"owner": "a"}).json()
    second = client.post("/api/jobs/claim", params={"owner": "b"}).json()
    assert first["claimed"] is True
    assert first["job"]["id"] == created["id"]
    assert first["credential_ttl_seconds"] == 600
    assert first["lease_ttl_seconds"] == 600
    assert second["claimed"] is False


def test_expired_write_does_not_change_the_row(client):
    with session() as db:
        job = enqueue(db, workspace_id="ws", job_type="segment_script", payload={"script": "一"})
        claimed = claim(db, "a", credential="cred", now=datetime.now(timezone.utc) - timedelta(minutes=11))
        assert claimed["job"]["id"] == job["id"]
        try:
            complete(db, job["id"], "a", {"table": []}, None, now=datetime.now(timezone.utc))
            raised = False
        except Exception as exc:  # noqa: BLE001
            raised = exc
        from sqlalchemy import text

        late = db.execute(text("SELECT status, output, lease_owner FROM jobs WHERE id = :id"), {"id": job["id"]}).mappings().one()
    assert getattr(raised, "code", None) == "lease"
    assert late["status"] == "leased"
    assert late["output"] is None
    assert late["lease_owner"] == "a"


def test_stranger_complete_is_rejected_on_the_http_route(client):
    created = client.post("/api/jobs", json={"workspace_id": "ws", "type": "write_prompt", "input": {"segment": 3}}).json()
    claimed = client.post("/api/jobs/claim", params={"owner": "agent-1"}).json()
    assert claimed["claimed"] is True
    rejected = client.post(
        f"/api/jobs/{created['id']}/complete",
        json={"owner": "stranger", "output": {"hack": True}, "error": None},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "lease"
    listed = client.post("/api/jobs/claim", params={"owner": "other"}).json()
    assert listed["claimed"] is False or listed["job"]["id"] != created["id"]
    again = client.post(
        f"/api/jobs/{created['id']}/complete",
        json={"owner": "agent-1", "output": {"prompt": "kept"}, "error": None},
    )
    assert again.status_code == 200
    assert again.json()["status"] == "succeeded"
    assert again.json()["output"] == '{"prompt": "kept"}'


def test_inspect_marks_lease_expired_when_attempts_are_used(client):
    with session() as db:
        job = enqueue(db, workspace_id="ws", job_type="extract_reference", payload={"note": "x"}, max_attempts=1)
        claim(db, "a", credential="cred", now=datetime.now(timezone.utc) - timedelta(minutes=11))
        changed = inspect(db, now=datetime.now(timezone.utc))
    assert changed[0]["id"] == job["id"]
    assert changed[0]["status"] == "failed"
    assert changed[0]["error"] == "lease_expired"


def test_accept_writes_product_and_accepted_at_together(client):
    created = client.post("/api/jobs", json={"workspace_id": "ws", "type": "write_prompt", "input": {"segment": 1}}).json()
    claimed = client.post("/api/jobs/claim", params={"owner": "a"}).json()
    client.post(
        f"/api/jobs/{created['id']}/complete",
        json={"owner": "a", "output": {"prompt": "red can on a skateboard"}, "error": None},
    )
    accepted = client.post(f"/api/jobs/{created['id']}/accept", json={"valid": True}).json()
    assert accepted["job"]["accepted_at"]
    assert accepted["product"]["prompt"] == "red can on a skateboard"
    assert accepted["product"]["origin_job_id"] == created["id"]
    assert claimed["job"]["attempt"] == 1


def test_invalid_prompt_writes_neither_product_nor_accepted_at(client):
    created = client.post("/api/jobs", json={"workspace_id": "ws", "type": "write_prompt", "input": {"segment": 1}}).json()
    client.post("/api/jobs/claim", params={"owner": "a"})
    client.post(f"/api/jobs/{created['id']}/complete", json={"owner": "a", "output": {"prompt": "short"}, "error": None})
    rejected = client.post(f"/api/jobs/{created['id']}/accept", json={"valid": False}).json()
    assert rejected["product"] is None
    assert rejected["job"]["accepted_at"] is None
    assert rejected["job"]["status"] == "failed"
    listed = client.get("/api/products", params={"q": "short"}).json()
    assert listed["items"] == []


def test_agent_cannot_insert_a_business_row(client):
    response = client.post("/api/agent/insert")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "forbidden"


def test_secret_never_enters_job_input(client):
    response = client.post("/api/jobs", json={"workspace_id": "ws", "type": "segment_script", "input": {"token": "raw"}})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "secret"
