"""Provider settings, local upload, frame alignment, and stubbed image/music jobs."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import server.app as app_module
from server.storage import Storage
from server.store import Store
from tests.test_integration import admin_headers


def boot(root: Path) -> TestClient:
    os.environ["CVGEN_DATA"] = str(root)
    os.environ["CVGEN_PUBLIC_BASE"] = "http://127.0.0.1:9"
    os.environ.pop("RUSTFS_ENDPOINT", None)
    os.environ.pop("CVGEN_IMAGE_BASE", None)
    os.environ.pop("CVGEN_IMAGE_KEY", None)
    os.environ.pop("CVGEN_IMAGE_WORKFLOW", None)
    os.environ.pop("CVGEN_MUSIC_BASE", None)
    os.environ.pop("CVGEN_MUSIC_KEY", None)
    os.environ.pop("CVGEN_MUSIC_WORKFLOW", None)
    app_module.DATA = root
    app_module.PUBLIC = "http://127.0.0.1:9"
    app_module.store = Store(root / "cvgen.sqlite")
    app_module.storage = Storage(root)
    from server.jobs import JobRunner

    app_module.runner = JobRunner(app_module.store, app_module.storage, app_module.PUBLIC, root)
    return TestClient(app_module.app)


def approve(client: TestClient, admin: dict) -> dict:
    started = client.post("/api/device/start").json()
    client.post(f"/api/device/{started['code']}/approve", headers=admin)
    token = client.get(f"/api/device/{started['code']}").json()["token"]
    return {"Authorization": f"Bearer {token}"}


def wait_job(client: TestClient, job_id: str, headers: dict) -> dict:
    deadline = time.time() + 8
    shown = {}
    while time.time() < deadline:
        shown = client.get(f"/api/job/{job_id}", headers=headers).json()
        if shown.get("status") in {"succeeded", "failed", "unknown"}:
            return shown
        time.sleep(0.05)
    return shown


def tiny_clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=480x480:d=2",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
        ],
        check=True,
    )


class CapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cvgen-cap-"))
        self.client = boot(self.root)
        self.admin = admin_headers(self.client)
        self.headers = approve(self.client, self.admin)
        self._restore = None

    def tearDown(self) -> None:
        if self._restore:
            import h3_client

            h3_client._request, h3_client.query, h3_client.download = self._restore

    def test_provider_settings_mask_key_and_override_env(self) -> None:
        os.environ["CVGEN_IMAGE_BASE"] = "http://env.example"
        os.environ["CVGEN_IMAGE_KEY"] = "env-secret-key"
        os.environ["CVGEN_IMAGE_WORKFLOW"] = "env-flow"
        listed = self.client.get("/api/settings/providers", headers=self.admin)
        self.assertEqual(listed.status_code, 200)
        image = next(item for item in listed.json()["items"] if item["capability"] == "image")
        self.assertTrue(image["configured"])
        self.assertEqual(image["key"], "••••-key")
        self.assertNotIn("env-secret-key", json.dumps(listed.json()))
        saved = self.client.post("/api/settings/providers", headers=self.admin, json={
            "capability": "image",
            "base": "http://saved.example",
            "key": "saved-secret-9999",
            "workflow": "image-flow",
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["base"], "http://saved.example")
        self.assertEqual(saved.json()["key"], "••••9999")
        self.assertNotIn("saved-secret-9999", json.dumps(saved.json()))
        canvas = self.client.get("/api/canvas", headers=self.headers).json()
        self.assertNotIn("saved-secret-9999", json.dumps(canvas))
        self.assertNotIn("env-secret-key", json.dumps(canvas))
        from server.providers import resolve

        resolved = resolve(app_module.store, "image")
        self.assertEqual(resolved["base"], "http://saved.example")
        self.assertEqual(resolved["workflow"], "image-flow")

    def test_unconfigured_image_and_music_refuse(self) -> None:
        shot = self.client.post("/api/entity", headers=self.headers, json={
            "type": "Shot",
            "data": {"title": "锚定", "size": "特写", "angle": "平视", "action": "产品转出", "duration": 5},
        })
        refused = self.client.post("/api/image", headers=self.headers, json={"target_id": shot.json()["id"]})
        self.assertEqual(refused.status_code, 400)
        music = self.client.post("/api/music", headers=self.headers, json={"detail": {"text": "副歌"}})
        self.assertEqual(music.status_code, 400)

    def test_upload_frame_compose_image_music_mix_subtitle_and_check(self) -> None:
        self._stub()
        self.client.post("/api/settings/providers", headers=self.admin, json={
            "capability": "image", "base": "http://image.test", "key": "image-key", "workflow": "image-flow",
        })
        self.client.post("/api/settings/providers", headers=self.admin, json={
            "capability": "music", "base": "http://music.test", "key": "music-key", "workflow": "music-flow",
        })
        image = self.root / "product.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nproduct")
        uploaded = self.client.post(
            "/api/media",
            headers=self.headers,
            files={"file": ("product.png", image.read_bytes(), "image/png")},
            data={"kind": "image", "role": "首帧", "title": "开场"},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["type"], "Reference")
        self.assertTrue(uploaded.json()["object_key"].startswith("references/"))
        video = self.root / "local.mp4"
        tiny_clip(video)
        clip_up = self.client.post(
            "/api/media",
            headers=self.headers,
            files={"file": ("local.mp4", video.read_bytes(), "video/mp4")},
            data={"kind": "video", "title": "本机成片"},
        )
        self.assertEqual(clip_up.json()["type"], "Clip")
        self.assertTrue(clip_up.json()["object_key"].startswith("clips/"))
        shot = self.client.post("/api/entity", headers=self.headers, json={
            "type": "Shot",
            "data": {"title": "续接", "size": "中景", "angle": "平视", "action": "产品沿边缘转出", "duration": 5},
        }).json()
        self.client.post("/api/link", headers=self.headers, json={
            "name": "references", "source_id": shot["id"], "target_id": uploaded.json()["id"],
        })
        last = self.client.post("/api/entity", headers=self.headers, json={
            "type": "Reference",
            "data": {"title": "结尾", "role": "尾帧"},
        }).json()
        self.client.post("/api/link", headers=self.headers, json={
            "name": "references", "source_id": shot["id"], "target_id": last["id"],
        })
        plan = self.client.get(f"/api/shot/{shot['id']}/compose", headers=self.headers).json()
        self.assertIn("参考图 1 对齐 0.00 秒", plan["prompt"].split("【核心创意】")[0])
        self.assertIn("参考图 2 对齐 5.00 秒", plan["prompt"])
        framed = self.client.post("/api/frame", headers=self.headers, json={
            "target_id": clip_up.json()["id"], "detail": {"at": "last", "role": "空间"},
        })
        done_frame = wait_job(self.client, framed.json()["job_id"], self.headers)
        self.assertEqual(done_frame["status"], "succeeded", done_frame)
        reference = self.client.get(f"/api/entity/{done_frame['detail']['reference_id']}", headers=self.headers).json()
        self.assertEqual(reference["data"]["role"], "空间")
        self.assertTrue(reference["object_key"].startswith("references/"))
        image_job = self.client.post("/api/image", headers=self.headers, json={
            "target_id": shot["id"], "detail": {"role": "细节"},
        })
        done_image = wait_job(self.client, image_job.json()["job_id"], self.headers)
        self.assertEqual(done_image["status"], "succeeded", done_image)
        self.assertTrue(done_image["detail"]["object_key"].startswith("references/"))
        self.assertNotIn("image-key", json.dumps(done_image))
        music_job = self.client.post("/api/music", headers=self.headers, json={"detail": {"text": "产品转出"}})
        done_music = wait_job(self.client, music_job.json()["job_id"], self.headers)
        self.assertEqual(done_music["status"], "succeeded", done_music)
        self.assertTrue(done_music["detail"]["object_key"].startswith("clips/"))
        edit = self.client.post("/api/entity", headers=self.headers, json={
            "type": "Edit",
            "data": {
                "title": "成片",
                "music": done_music["detail"]["clip_id"],
                "lines": ["产品转出"],
            },
        }).json()
        self.client.post("/api/link", headers=self.headers, json={
            "name": "uses_clip", "source_id": edit["id"], "target_id": clip_up.json()["id"],
        })
        mixed = self.client.post("/api/edit", headers=self.headers, json={"target_id": edit["id"], "detail": {"op": "mix"}})
        done_mix = wait_job(self.client, mixed.json()["job_id"], self.headers)
        self.assertEqual(done_mix["status"], "succeeded", done_mix)
        self.assertIn("volume=8dB", done_mix["detail"]["mix"])
        self.assertIn("alimiter=limit=0.891", done_mix["detail"]["mix"])
        self.assertNotEqual(done_mix["detail"]["object_key"], clip_up.json()["object_key"])
        subtitled = self.client.post("/api/edit", headers=self.headers, json={"target_id": edit["id"], "detail": {"op": "subtitle"}})
        done_sub = wait_job(self.client, subtitled.json()["job_id"], self.headers)
        self.assertEqual(done_sub["status"], "succeeded", done_sub)
        self.assertEqual(done_sub["detail"]["lines"], ["产品转出"])
        empty = self.client.post("/api/entity", headers=self.headers, json={"type": "Edit", "data": {"title": "无声"}}).json()
        self.client.post("/api/link", headers=self.headers, json={
            "name": "uses_clip", "source_id": empty["id"], "target_id": clip_up.json()["id"],
        })
        refused = self.client.post("/api/edit", headers=self.headers, json={"target_id": empty["id"], "detail": {"op": "mix"}})
        done_refuse = wait_job(self.client, refused.json()["job_id"], self.headers)
        self.assertEqual(done_refuse["status"], "failed")
        self.assertIn("没有配乐", done_refuse["detail"]["error"])
        wide = self.root / "wide.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x180:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(wide)],
            check=True,
        )
        wide_up = self.client.post(
            "/api/media",
            headers=self.headers,
            files={"file": ("wide.mp4", wide.read_bytes(), "video/mp4")},
            data={"kind": "video", "title": "超规格"},
        )
        checked = self.client.post("/api/check", headers=self.headers, json={"target_id": wide_up.json()["id"]})
        done_check = wait_job(self.client, checked.json()["job_id"], self.headers)
        self.assertEqual(done_check["status"], "succeeded", done_check)
        self.assertFalse(done_check["detail"]["passed"])
        self.assertTrue(any("分辨率" in item for item in done_check["detail"]["problems"]))

    def _stub(self) -> None:
        import h3_client

        self._restore = (h3_client._request, h3_client.query, h3_client.download)

        def fake_request(url, token, body=None, timeout=120):
            return 200, {"data": {"task_id": "stub-task"}}

        def fake_query(task_id):
            return {"status": "succeeded", "video_url": "http://stub.local/file"}

        def fake_download(url, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.suffix == ".png":
                dest.write_bytes(b"\x89PNG\r\n\x1a\nstub")
            else:
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=1", "-c:a", "pcm_s16le", str(dest)],
                    check=True,
                )
            return dest

        h3_client._request = fake_request
        h3_client.query = fake_query
        h3_client.download = fake_download


if __name__ == "__main__":
    unittest.main()
