"""People, roles, devices and API keys."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app

from .conftest import Api, make_device, make_user


def test_setup_only_once_and_login(client):
    assert client.get("/api/auth/status").json()["setup_needed"] is True
    assert client.post("/api/auth/setup", json={"username": "a", "password": "short"}).status_code == 400
    assert client.post("/api/auth/setup", json={"username": "admin", "password": "adminpass1"}).status_code == 200
    assert client.post("/api/auth/setup", json={"username": "x", "password": "adminpass1"}).status_code == 409
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"username": "admin", "password": "wrongpass1"}).status_code == 401
    assert other.post("/api/auth/login", json={"username": "admin", "password": "adminpass1"}).status_code == 200
    assert other.get("/api/auth/me").json()["role"] == "admin"


def test_cookie_writes_need_csrf_header(admin):
    bare = Api(admin.client)
    bare.request("POST", "/api/workspaces", json={"name": "无头"}, expect=403)
    admin.post("/api/workspaces", {"name": "有头"})


def test_two_sessions_coexist(admin):
    second = TestClient(app)
    assert second.post("/api/auth/login", json={"username": "admin", "password": "adminpass1"}).status_code == 200
    assert admin.get("/api/auth/me")["role"] == "admin"
    assert second.get("/api/auth/me").json()["role"] == "admin"


def test_roles(admin, fresh):
    producer = make_user(admin, "pro", "producer")
    reviewer = make_user(admin, "rev", "reviewer")
    producer.request("GET", "/api/activity", expect=403)
    reviewer.get("/api/activity")
    producer.request("GET", "/api/admin/users", expect=403)
    reviewer.request("POST", "/api/works", json={"workspace_id": fresh["workspace_id"], "title": "x"}, expect=403)


def test_device_flow_token_once_and_expiry(admin, client):
    start = client.post("/api/device/start", json={"name": "笔记本"}).json()
    assert len(start["user_code"]) == 9 and start["approve_path"].startswith("/approve/")
    poll = {"device_id": start["device_id"], "poll_secret": start["poll_secret"]}
    assert client.post("/api/device/poll", json=poll).json()["status"] == "pending"
    assert client.post("/api/device/poll", json={**poll, "poll_secret": "guess"}).status_code == 404
    info = admin.get(f"/api/devices/code/{start['user_code'].lower().replace('-', '')}")
    assert info["name"] == "笔记本"
    admin.post(f"/api/devices/code/{start['user_code']}/approve")
    token = client.post("/api/device/poll", json=poll).json()["token"]
    assert client.post("/api/device/poll", json=poll).json()["status"] == "claimed"
    device = Api(TestClient(app), {"Authorization": f"Bearer {token}"})
    assert device.get("/api/auth/me")["role"] == "agent"
    device.request("POST", "/api/admin/users", json={"username": "x", "password": "xxxxxxxx1"}, expect=403)
    devices = admin.get("/api/devices")["items"]
    admin.post(f"/api/devices/{devices[0]['id']}/revoke")
    device.request("GET", "/api/auth/me", expect=401)


def test_two_devices_can_be_online(admin):
    first = make_device(admin, "one")
    second = make_device(admin, "two")
    assert first.get("/api/auth/me")["kind"] == "device"
    assert second.get("/api/auth/me")["kind"] == "device"


def test_expired_code_cannot_be_approved(admin, client):
    from sqlalchemy import update

    from server import db

    start = client.post("/api/device/start", json={}).json()
    with db.tx() as conn:
        conn.execute(update(db.devices).where(db.devices.c.id == start["device_id"]).values(expires_at=db.now()))
    admin.request("POST", f"/api/devices/code/{start['user_code']}/approve", expect=410)


def test_api_key_scopes_and_workspace(admin, fresh):
    other_ws = admin.post("/api/workspaces", {"name": "别的工作区"})
    created = admin.post("/api/admin/keys", {"name": "下游服务", "workspace_id": fresh["workspace_id"],
                                             "scopes": ["runs:read"]})
    key = Api(TestClient(app), {"Authorization": f"Bearer {created['key']}"})
    assert key.get("/api/workspaces")["items"][0]["id"] == fresh["workspace_id"]
    key.request("GET", f"/api/assets?workspace_id={other_ws['id']}", expect=403)
    key.request("POST", "/v1/runs", json={"workflow_id": "wf_x"}, expect=403)
    admin.post(f"/api/admin/keys/{created['id']}/revoke")
    key.request("GET", "/v1/workflows", expect=401)


def test_password_change_signs_out_other_sessions(admin):
    other = TestClient(app)
    other.post("/api/auth/login", json={"username": "admin", "password": "adminpass1"})
    admin.post("/api/auth/password", {"password": "adminpass1", "next_password": "adminpass2"})
    assert other.get("/api/auth/me").status_code == 401
    assert admin.get("/api/auth/me")["role"] == "admin"
