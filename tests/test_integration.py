"""Drive the shipped app: story seed, compose, generate refusal, and shared canvas."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import server.app as app_module
from server.storage import Storage
from server.store import Store


SKILL_NAMES = (
    "cvgen-3d",
    "cvgen-brand",
    "cvgen-check",
    "cvgen-continuity",
    "cvgen-edit",
    "cvgen-episode",
    "cvgen-h3-prompt",
    "cvgen-handdrawn",
    "cvgen-index",
    "cvgen-learn",
    "cvgen-local",
    "cvgen-modes",
    "cvgen-music",
    "cvgen-product-ad",
    "cvgen-reverse",
    "cvgen-style",
    "cvgen-zero",
)
FORBIDDEN = ("http://", "https://", "curl ", "供应商", "轮询", "task_id", "Bearer ")


def admin_headers(client: TestClient) -> dict:
    setup = client.post("/api/admin/setup", json={"username": "admin", "password": "admin-pass"})
    assert setup.status_code == 200, setup.text
    return {"Authorization": f"Bearer {setup.json()['token']}"}


def approve_device(client: TestClient, code: str, headers: dict):
    response = client.post(f"/api/device/{code}/approve", headers=headers)
    assert response.status_code == 200, response.text
    return response


def boot(root: Path):
    os.environ["CVGEN_DATA"] = str(root)
    os.environ["CVGEN_PUBLIC_BASE"] = "http://127.0.0.1:9"
    os.environ.pop("RUSTFS_ENDPOINT", None)
    app_module.DATA = root
    app_module.PUBLIC = "http://127.0.0.1:9"
    app_module.store = Store(root / "cvgen.sqlite")
    app_module.storage = Storage(root)
    from server.jobs import JobRunner

    app_module.runner = JobRunner(app_module.store, app_module.storage, app_module.PUBLIC, root)
    return TestClient(app_module.app)


class StoryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cvgen-api-"))
        self.client = boot(self.root)
        admin = admin_headers(self.client)
        started = self.client.post("/api/device/start").json()
        approve_device(self.client, started["code"], admin)
        token = self.client.get(f"/api/device/{started['code']}").json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.admin = admin

    def test_unauthorised_story_is_refused(self) -> None:
        response = self.client.post("/api/stories/zero")
        self.assertEqual(response.status_code, 401)

    def test_story_compose_canvas_and_second_generate(self) -> None:
        seeded = self.client.post("/api/stories/zero", headers=self.headers)
        self.assertEqual(seeded.status_code, 200)
        shot_id = seeded.json()["shot_id"]
        plan = self.client.get(f"/api/shot/{shot_id}/compose", params={"resolution": "768p横"}, headers=self.headers)
        self.assertEqual(plan.status_code, 200)
        body = plan.json()
        self.assertEqual(body["duration"], 15)
        self.assertEqual(body["resolution"], "768p横")
        self.assertEqual(body["prompt"].count("正向："), 3)
        self.assertIn("【参考素材说明】", body["prompt"])
        self.assertTrue(body["can_submit"])
        self.assertTrue(any(item["role"] == "细节" for item in body["references"]))

        view = self.client.get("/api/view", headers=self.admin).json()
        canvas = self.client.get("/api/canvas", headers=self.headers).json()
        self.assertEqual(canvas["nodes"], view["nodes"])
        self.assertEqual(canvas["edges"], view["edges"])
        self.assertEqual(canvas["jobs"], view["jobs"])
        shot = next(node for node in canvas["nodes"] if node["id"] == shot_id)
        self.assertEqual(shot["status"], "未生成")
        self.assertGreaterEqual(len(canvas["edges"]), 8)
        self.assertIn("cvgen-zero", canvas["skills"])

        extra = self.client.post(
            "/api/entity",
            headers=self.headers,
            json={"type": "Camera", "data": {"title": "第二种运镜", "move": "快速推进"}},
        )
        self.assertEqual(extra.status_code, 200)
        second_camera = self.client.post(
            "/api/link",
            headers=self.headers,
            json={"name": "shot_with", "source_id": shot_id, "target_id": extra.json()["id"], "note": "重复运镜"},
        )
        self.assertEqual(second_camera.status_code, 400)
        self.assertIn("一种运镜", second_camera.json()["detail"])

        bad_type = self.client.post(
            "/api/entity",
            headers=self.headers,
            json={"type": "NotAType", "data": {"title": "非法"}},
        )
        self.assertEqual(bad_type.status_code, 400)

        app_module.store.add_job("generate", shot_id, "queued", {"resolution": "768p横"})
        duplicate = self.client.post(
            "/api/generate",
            headers=self.headers,
            json={"shot_id": shot_id, "resolution": "768p横"},
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("不能再次提交", duplicate.json()["detail"])

        again = self.client.get("/api/view", headers=self.admin).json()
        again_canvas = self.client.get("/api/canvas", headers=self.headers).json()
        self.assertEqual(
            [(node["id"], node["status"]) for node in again["nodes"]],
            [(node["id"], node["status"]) for node in again_canvas["nodes"]],
        )
        self.assertEqual(
            [(edge["id"], edge["source_id"], edge["target_id"]) for edge in again["edges"]],
            [(edge["id"], edge["source_id"], edge["target_id"]) for edge in again_canvas["edges"]],
        )
        self.assertEqual(
            [(job["id"], job["status"], job["target_id"]) for job in again["jobs"]],
            [(job["id"], job["status"], job["target_id"]) for job in again_canvas["jobs"]],
        )
        queued = next(node for node in again["nodes"] if node["id"] == shot_id)
        self.assertEqual(queued["status"], "排队")


class GuardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cvgen-guard-"))
        self.client = boot(self.root)
        (self.root / "secret.txt").write_text("TOKEN-LEAK", encoding="utf-8")
        (self.root / "clips").mkdir(parents=True, exist_ok=True)
        (self.root / "clips" / "ok.mp4").write_bytes(b"clip-bytes")

    def test_anonymous_passthrough_stays_closed_and_media_rejects_traversal(self) -> None:
        denied = self.client.post("/api/settings/passthrough", params={"enabled": True})
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(app_module.store.setting("ffmpeg_passthrough", "0"), "0")
        for key in ("..%2fsecret.txt", "%2e%2e/secret.txt", "%2e%2e%2fsecret.txt"):
            leaked = self.client.get(f"/media/clips/{key}")
            self.assertEqual(leaked.status_code, 401, key)
            self.assertNotIn(b"TOKEN-LEAK", leaked.content)
        normalized = self.client.get("/media/clips/foo/../../secret.txt")
        self.assertIn(normalized.status_code, {401, 404})
        self.assertNotIn(b"TOKEN-LEAK", normalized.content)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/no-such-page").status_code, 404)
        locked = self.client.get("/media/clips/ok.mp4")
        self.assertEqual(locked.status_code, 401)
        self.assertNotIn(b"clip-bytes", locked.content)

        admin = admin_headers(self.client)
        kept = self.client.get("/media/clips/ok.mp4", headers=admin)
        self.assertEqual(kept.status_code, 200)
        self.assertEqual(kept.content, b"clip-bytes")
        for key in ("..%2fsecret.txt", "%2e%2e/secret.txt", "%2e%2e%2fsecret.txt", "foo/../../secret.txt"):
            leaked = self.client.get(f"/media/clips/{key}", headers=admin)
            self.assertEqual(leaked.status_code, 404, key)
            self.assertNotIn(b"TOKEN-LEAK", leaked.content)
        started = self.client.post("/api/device/start").json()
        approve_device(self.client, started["code"], admin)
        token = self.client.get(f"/api/device/{started['code']}").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        opened = self.client.post("/api/settings/passthrough", params={"enabled": True}, headers=headers)
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(app_module.store.setting("ffmpeg_passthrough", "0"), "1")
        ffmpeg = self.client.post("/api/ffmpeg", headers=headers, json={"detail": {"args": ["-version"]}})
        self.assertEqual(ffmpeg.status_code, 200)
        job_id = ffmpeg.json()["job_id"]
        deadline = time.time() + 8
        while time.time() < deadline:
            shown = self.client.get(f"/api/job/{job_id}", headers=headers)
            if shown.status_code == 200 and shown.json()["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        self.assertEqual(shown.json()["status"], "succeeded")
        self.assertEqual(shown.json()["detail"]["result"]["code"], 0)
        closed = self.client.post("/api/settings/passthrough", params={"enabled": False}, headers=headers)
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(app_module.store.setting("ffmpeg_passthrough", "0"), "0")
        blocked = self.client.post("/api/ffmpeg", headers=headers, json={"detail": {"args": ["-version"]}})
        self.assertEqual(blocked.status_code, 403)


class SkillFileTests(unittest.TestCase):
    def test_skills_only_describe_cvgen_operations(self) -> None:
        folder = Path(__file__).resolve().parents[1] / "skills"
        names = sorted(path.stem for path in folder.glob("*.md"))
        self.assertEqual(tuple(names), SKILL_NAMES)
        for path in folder.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIn("cvgen ", text)
            for token in FORBIDDEN:
                self.assertNotIn(token, text, path.name)
        zero = (folder / "cvgen-zero.md").read_text(encoding="utf-8")
        for command in ("cvgen story", "cvgen shot compose", "cvgen generate", "cvgen job show"):
            self.assertIn(command, zero)


if __name__ == "__main__":
    unittest.main()
