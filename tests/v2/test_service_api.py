"""Service API v1: API keys, idempotent runs, outputs with absolute URLs, signed callbacks."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import update

from server import db
from server.app import app
from server.engine.worker import maintenance
from server.samples import ZERO_FIXTURE, seed_samples
from server.security import webhook_signature

from .conftest import Api, run_worker


class Receiver(BaseHTTPRequestHandler):
    received: list = []

    def do_POST(self):  # noqa: N802 - http.server API
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Receiver.received.append({"headers": dict(self.headers), "body": body})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def _key(admin, workspace_id: str, scopes: list[str]) -> Api:
    created = admin.post("/api/admin/keys", {"name": "下游", "workspace_id": workspace_id, "scopes": scopes})
    return Api(TestClient(app), {"Authorization": f"Bearer {created['key']}"})


def test_service_api_end_to_end(admin, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    zero = seeded["workflows"]["zero-snow"]["workflow_id"]
    admin.post(f"/api/workflows/{zero}/versions/1/publish")
    with db.tx() as conn:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == "llm.default")
                     .values(options={"replies": {"adapt": ZERO_FIXTURE}}))
    service = _key(admin, fresh["workspace_id"], ["runs:write", "runs:read", "assets:write"])

    listed = service.get("/v1/workflows")["items"]
    assert [item["id"] for item in listed] == [zero]
    version = service.get(f"/v1/workflows/{zero}/versions/1")
    assert version["inputs"]["required"] == ["passage"]
    service.request("GET", f"/v1/workflows/{seeded['workflows']['product-ad']['workflow_id']}/versions/1", expect=404)

    path = Path(tempfile.mkdtemp()) / "x.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=32x32", "-frames:v", "1",
                    str(path)], check=True)
    uploaded = service.request("POST", "/v1/assets/uploads", data={"label": "图"},
                               files={"file": ("x.png", io.BytesIO(path.read_bytes()), "image/png")}).json()
    assert uploaded["id"].startswith("art_")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Receiver.received.clear()
    callback = f"http://127.0.0.1:{server.server_address[1]}/hook"
    body = {"workflow_id": zero, "inputs": {"passage": "原文"}, "callback_url": callback}
    first = service.request("POST", "/v1/runs", json=body, headers={"Idempotency-Key": "order-1"}, expect=202).json()
    again = service.request("POST", "/v1/runs", json=body, headers={"Idempotency-Key": "order-1"}, expect=202).json()
    assert first["id"] == again["id"]
    service.request("POST", "/v1/runs", json={"workflow_id": zero, "inputs": {}}, expect=400)

    run_worker()
    maintenance()
    server.shutdown()
    status = service.get(f"/v1/runs/{first['id']}")
    assert status["status"] == "succeeded" and status["stages"][0]["done"] == 1
    outputs = service.get(f"/v1/runs/{first['id']}/outputs")
    url = outputs["outputs"]["video"][0]["url"]
    assert url.startswith("http://testserver/media/")
    assert TestClient(app).get(url.replace("http://testserver", "")).status_code == 200

    events = [json.loads(item["body"])["event"] for item in Receiver.received]
    assert "run.started" in events and "run.succeeded" in events
    sample = Receiver.received[-1]
    stamp = int(sample["headers"]["X-CVGEN-Timestamp"])
    assert sample["headers"]["X-CVGEN-Signature"] == f"sha256={webhook_signature(sample['body'], stamp)}"

    other = _key(admin, fresh["workspace_id"], ["runs:read"])
    other.request("GET", f"/v1/runs/{first['id']}", expect=404)
    assert other.get("/v1/runs")["items"] == []


def test_openapi_lists_v1(client):
    paths = client.get("/v1/openapi.json").json()["paths"]
    assert "/v1/runs" in paths and "/v1/runs/{run_id}/outputs" in paths
