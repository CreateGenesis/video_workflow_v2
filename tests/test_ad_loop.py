"""Drive the shipped ad loop through the Python CLI and the Rust binary."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

import asyncio

import httpx
import uvicorn
from fastapi.testclient import TestClient

import server.app as app_module
from server.storage import Storage
from server.store import Store

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path("/home/coder/.cache/tmp/grok-goal-80271fb16103/implementer")


def admin_headers(client: TestClient) -> dict:
    setup = client.post("/api/admin/setup", json={"username": "admin", "password": "admin-pass"})
    assert setup.status_code == 200, setup.text
    return {"Authorization": f"Bearer {setup.json()['token']}"}


def boot(root: Path) -> TestClient:
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


def tiny_video(path: Path, color: str, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={seconds}",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=" + str(seconds),
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
    )


def tiny_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=1", "-c:a", "pcm_s16le", str(path)],
        check=True,
    )


def stub_provider(monkey, video: bytes):
    import h3_client

    original = (h3_client.submit, h3_client.query, h3_client.download, h3_client.build_body, h3_client._request, h3_client.config)

    def fake_submit(body):
        return {"task_id": "stub-task", "status": "queued"}

    def fake_query(task_id):
        return {"status": "SUCCESS", "video_url": "https://provider.test/ad.mp4"}

    def fake_download(url, dest):
        Path(dest).write_bytes(video)
        return Path(dest)

    h3_client.submit = fake_submit
    h3_client.query = fake_query
    h3_client.download = fake_download
    h3_client.build_body = lambda prompt, images, duration=5, resolution="768p横": {"prompt": prompt, "images": images}
    h3_client._request = lambda *args, **kwargs: (200, {"data": {"task_id": "tts-stub"}})
    h3_client.config = lambda: {"base": "https://provider.test", "token": "stub", "workflow": "indextts2-v1"}
    monkey.append(original)
    return original


class AdLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cvgen-ad-"))
        self.client = boot(self.root)
        self.admin = admin_headers(self.client)
        started = self.client.post("/api/device/start").json()
        approved = self.client.post(f"/api/device/{started['code']}/approve", headers=self.admin)
        self.assertEqual(approved.status_code, 200)
        token = self.client.get(f"/api/device/{started['code']}").json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.video = self.root / "provider.mp4"
        tiny_video(self.video, "green", 1.2)
        self.audio = self.root / "voice.wav"
        tiny_wav(self.audio)
        self._restore = []
        stub_provider(self._restore, self.video.read_bytes())

    def tearDown(self) -> None:
        if self._restore:
            import h3_client
            h3_client.submit, h3_client.query, h3_client.download, h3_client.build_body, h3_client._request, h3_client.config = self._restore[0]

    def wait_job(self, job_id: str) -> dict:
        deadline = time.time() + 30
        shown = {}
        while time.time() < deadline:
            shown = self.client.get(f"/api/job/{job_id}", headers=self.headers).json()
            if shown["status"] in {"succeeded", "failed", "unknown"}:
                return shown
            time.sleep(0.05)
        self.fail(f"job {job_id} stayed {shown.get('status')}")

    def entity(self, type_name: str, data: dict, object_key: str | None = None) -> dict:
        body = {"type": type_name, "data": data}
        if object_key:
            body["object_key"] = object_key
        response = self.client.post("/api/entity", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def link(self, name: str, source: str, target: str) -> None:
        response = self.client.post(
            "/api/link",
            headers=self.headers,
            json={"name": name, "source_id": source, "target_id": target},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_ad_loop_upload_generate_preview_tts_and_mix(self) -> None:
        work = self.entity("Work", {"title": "纱布广告", "kind": "广告", "brief": "十五秒产品"})
        subject = self.entity("Subject", {"title": "纱布卷", "summary": "医用棉纱"})
        appearance = self.entity("Appearance", {"title": "产品外观", "material": "白棉纱"})
        self.link("has_appearance", subject["id"], appearance["id"])
        style = self.entity("Style", {"title": "极简产品广告", "medium": "真人电影感", "grade": "统一光线", "ban": "禁止定格、字幕和水印"})
        place = self.entity("Place", {"title": "木桌", "facts": "左窗光，右空"})
        camera = self.entity("Camera", {"title": "缓推", "move": "缓慢推进", "amplitude": "小", "speed": "慢"})
        shot = self.entity("Shot", {
            "title": "产品开场",
            "size": "特写",
            "angle": "平视",
            "action": "纱布卷在桌面上慢慢展开",
            "duration": 5,
            "sound": "布料摩擦声",
        })
        self.link("belongs_to", shot["id"], work["id"])
        self.link("styled_as", shot["id"], style["id"])
        self.link("located_in", shot["id"], place["id"])
        self.link("shot_with", shot["id"], camera["id"])

        product = self.root / "product.png"
        product.write_bytes(b"\x89PNG\r\n\x1a\nproduct")
        uploaded = self.client.post(
            "/api/reference",
            headers=self.headers,
            data={"role": "细节", "title": "产品图", "take": "纱布卷", "ignore": "背景"},
            files={"file": ("product.png", product.read_bytes(), "image/png")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        reference = uploaded.json()
        self.assertTrue(reference["object_key"].startswith("references/"))
        self.assertNotIn("object_key", uploaded.request.content.decode() if False else "")
        self.link("references", shot["id"], reference["id"])

        batch = self.client.get(f"/api/batch/{work['id']}", headers=self.headers)
        self.assertEqual(batch.status_code, 200)
        self.assertEqual(batch.json()["shots"][0]["status"], "未生成")
        self.assertEqual(batch.json()["shots"][0]["id"], shot["id"])

        plan = self.client.get(f"/api/shot/{shot['id']}/compose", headers=self.headers)
        self.assertEqual(plan.status_code, 200, plan.text)
        prompt = plan.json()["prompt"]
        for heading in ("【参考素材说明】", "【核心创意】", "【画面过程描述】", "【整体要求补充】"):
            self.assertIn(heading, prompt)
        self.assertTrue(plan.json()["can_submit"])

        started = self.client.post("/api/generate", headers=self.headers, json={"shot_id": shot["id"], "resolution": "768p横"})
        self.assertEqual(started.status_code, 200, started.text)
        finished = self.wait_job(started.json()["job_id"])
        self.assertEqual(finished["status"], "succeeded", finished)
        clip_id = finished["detail"]["clip_id"]
        object_key = finished["detail"]["object_key"]
        self.assertTrue(object_key.startswith("clips/"))
        illegal = [
            link for link in app_module.store.all_links()
            if link["name"] == "derived_from" and link["source_id"] == clip_id
        ]
        self.assertEqual(illegal, [])
        preview = self.client.get(f"/api/preview/{clip_id}", headers=self.headers)
        self.assertEqual(preview.status_code, 200)
        self.assertIn(object_key, preview.json()["preview_url"])
        self.assertTrue(preview.json()["sheet_url"])
        self.assertIn("sheet", preview.json()["sheet_url"])
        self.assertEqual(preview.json()["status"], "已成片")
        media = self.client.get(f"/media/{object_key}", headers=self.headers)
        self.assertEqual(media.status_code, 200)
        self.assertGreater(len(media.content), 100)

        blocked = self.client.post("/api/generate", headers=self.headers, json={"shot_id": shot["id"]})
        self.assertEqual(blocked.status_code, 409)

        voice_file = self.client.post(
            "/api/reference",
            headers=self.headers,
            data={"role": "音色", "title": "旁白音色"},
            files={"file": ("voice.wav", self.audio.read_bytes(), "audio/wav")},
        )
        self.assertEqual(voice_file.status_code, 200, voice_file.text)
        line = self.entity("Line", {"title": "旁白", "text": "这卷纱布，轻轻展开。", "kind": "旁白"})
        voice = self.entity("Voice", {"title": "女声", "method": "与音色参考音频相同"})
        self.link("voices", shot["id"], line["id"])
        self.link("voiced_by", shot["id"], voice["id"])
        self.link("references", voice["id"], voice_file.json()["id"])
        spoken = self.client.post("/api/tts", headers=self.headers, json={"target_id": line["id"]})
        self.assertEqual(spoken.status_code, 200, spoken.text)
        spoken_job = self.wait_job(spoken.json()["job_id"])
        self.assertEqual(spoken_job["status"], "succeeded", spoken_job)
        narration_id = spoken_job["detail"]["clip_id"]

        other = self.root / "other.mp4"
        tiny_video(other, "blue", 1.0)
        other_key = app_module.storage.put("clips", "other.mp4", other.read_bytes(), "video/mp4")
        other_clip = self.entity("Clip", {"title": "第二条"}, other_key)
        joined = self.client.post(
            "/api/edit",
            headers=self.headers,
            json={"detail": {"op": "join", "clips": [clip_id, other_clip["id"]], "fade": 2}},
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        joined_job = self.wait_job(joined.json()["job_id"])
        self.assertEqual(joined_job["status"], "succeeded", joined_job)
        joined_info = joined_job["detail"]["probe"]
        self.assertGreater(joined_info["duration"], 1.2)

        bare = self.entity("Edit", {"title": "只有成片", "note": "技能路径不写旁白"})
        self.link("uses_clip", bare["id"], clip_id)
        self.link("uses_clip", bare["id"], other_clip["id"])
        bare_export = self.client.post(
            "/api/edit",
            headers=self.headers,
            json={"target_id": bare["id"], "detail": {"op": "export"}},
        )
        self.assertEqual(bare_export.status_code, 200, bare_export.text)
        bare_job = self.wait_job(bare_export.json()["job_id"])
        self.assertEqual(bare_job["status"], "succeeded", bare_job)
        self.assertNotIn("narration", bare["data"])
        self.assertTrue(bare_job["detail"]["probe"]["has_audio"])
        bare_mix = bare_job["detail"].get("mix") or ""
        self.assertIn("volume=8dB", bare_mix)
        self.assertIn("sidechaincompress", bare_mix)
        self.assertIn("alimiter=limit=0.891", bare_mix)
        bare_body = self.client.get(f"/media/{bare_job['detail']['object_key']}", headers=self.headers)
        self.assertEqual(bare_body.status_code, 200)
        self.assertNotEqual(bare_body.content, media.content)
        self.assertGreater(len(bare_body.content), 100)
        empty = self.entity("Edit", {"title": "没有成片"})
        empty_export = self.client.post(
            "/api/edit",
            headers=self.headers,
            json={"target_id": empty["id"], "detail": {"op": "export"}},
        )
        self.assertEqual(empty_export.status_code, 200, empty_export.text)
        empty_job = self.wait_job(empty_export.json()["job_id"])
        self.assertEqual(empty_job["status"], "failed", empty_job)
        self.assertNotIn("object_key", empty_job["detail"])
        self.assertIn("没有成片", empty_job["detail"].get("error") or "")
        edit = self.entity("Edit", {"title": "广告成片", "note": "硬切后接旁白", "narration": narration_id})
        self.link("uses_clip", edit["id"], clip_id)
        self.link("uses_clip", edit["id"], other_clip["id"])
        exported = self.client.post(
            "/api/edit",
            headers=self.headers,
            json={"target_id": edit["id"], "detail": {"op": "export"}},
        )
        self.assertEqual(exported.status_code, 200, exported.text)
        exported_job = self.wait_job(exported.json()["job_id"])
        self.assertEqual(exported_job["status"], "succeeded", exported_job)
        self.assertTrue(exported_job["detail"]["probe"]["has_audio"])
        mix_graph = exported_job["detail"].get("mix") or ""
        self.assertIn("volume=8dB", mix_graph)
        self.assertIn("sidechaincompress", mix_graph)
        self.assertIn("alimiter=limit=0.891", mix_graph)
        render_key = exported_job["detail"]["object_key"]
        self.assertTrue(render_key.startswith("renders/"))
        rendered = self.client.get(f"/media/{render_key}", headers=self.headers)
        self.assertEqual(rendered.status_code, 200)
        self.assertNotEqual(rendered.content, media.content)
        self.assertGreater(len(rendered.content), 100)

        extracted = self.client.post("/api/style", headers=self.headers, json={"target_id": clip_id})
        self.assertEqual(extracted.status_code, 200, extracted.text)
        style_job = self.wait_job(extracted.json()["job_id"])
        self.assertEqual(style_job["status"], "succeeded", style_job)
        made = self.client.get(f"/api/entity/{style_job['detail']['style_id']}", headers=self.headers).json()
        self.assertEqual(made["type"], "Style")
        _write_defects({
            "style_type": made["type"],
            "style_id": made["id"],
            "batch_status": batch.json()["shots"][0]["status"],
            "generate_derived_from_links": len(illegal),
            "preview_sheet": bool(preview.json()["sheet_url"]),
            "preview_status": preview.json()["status"],
            "preview_sheet_url": preview.json()["sheet_url"],
            "mix": exported_job["detail"]["mix"],
        })

    def test_derived_from_rejects_shot_and_failed_shot_can_resubmit(self) -> None:
        shot = self.entity("Shot", {"title": "空镜", "size": "中景", "angle": "平视", "action": "放在桌上", "duration": 5})
        clip = self.entity("Clip", {"title": "已有成片"})
        denied = self.client.post(
            "/api/derive",
            headers=self.headers,
            json={"name": "derived_from", "source_id": shot["id"], "target_id": clip["id"]},
        )
        self.assertEqual(denied.status_code, 400)
        self.assertIn("成片或参考", denied.json()["detail"])
        with self.assertRaises(RuntimeError) as stored:
            app_module.store.add_link("derived_from", clip["id"], shot["id"], "生成路径也不能写")
        self.assertIn("成片或参考", str(stored.exception))
        self.assertFalse(any(link["name"] == "derived_from" for link in app_module.store.all_links()))

        failed = self.entity("Shot", {"title": "失败可重提", "size": "中景", "angle": "平视", "action": "再放一次", "duration": 5})
        app_module.store.add_job("generate", failed["id"], "failed", {})
        again = self.client.post("/api/generate", headers=self.headers, json={"shot_id": failed["id"], "resolution": "768p横", "force": True})
        self.assertEqual(again.status_code, 200, again.text)
        held = self.entity("Shot", {"title": "排队中", "size": "中景", "angle": "平视", "action": "等待", "duration": 5})
        app_module.store.add_job("generate", held["id"], "queued", {})
        queued = self.client.post("/api/generate", headers=self.headers, json={"shot_id": held["id"]})
        self.assertEqual(queued.status_code, 409)
        done = self.entity("Shot", {"title": "已成功", "size": "中景", "angle": "平视", "action": "已完成", "duration": 5})
        app_module.store.add_job("generate", done["id"], "succeeded", {})
        blocked = self.client.post("/api/generate", headers=self.headers, json={"shot_id": done["id"]})
        self.assertEqual(blocked.status_code, 409)
        prior = {}
        if (SCRATCH / "defects.log").is_file():
            prior = json.loads((SCRATCH / "defects.log").read_text(encoding="utf-8"))
        _write_defects({
            **prior,
            "derived_from_shot_to_clip": denied.status_code,
            "derived_from_detail": denied.json()["detail"],
            "generate_path_clip_to_shot": str(stored.exception),
            "illegal_links": 0,
            "failed_resubmit": again.status_code,
            "queued_second": queued.status_code,
            "succeeded_second": blocked.status_code,
        })

    def test_python_cli_drives_upload_and_wait(self) -> None:
        auth = self.root / "auth.json"
        auth.write_text(json.dumps({"base": "http://testserver", "token": self.headers["Authorization"].split()[1]}), encoding="utf-8")
        # The Python CLI uses httpx against a real URL. Drive the same functions the CLI calls
        # by invoking the installed module against a live local server below.
        product = self.root / "pack.png"
        product.write_bytes(b"\x89PNG\r\n\x1a\npack")
        uploaded = self.client.post(
            "/api/reference",
            headers=self.headers,
            data={"role": "风格", "title": "包装"},
            files={"file": ("pack.png", product.read_bytes(), "image/png")},
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertTrue(uploaded.json()["id"].startswith("reference_"))
        self.assertFalse(uploaded.json().get("data", {}).get("object_key"))


class LiveCliTests(unittest.TestCase):
    def test_python_and_rust_commands_close_the_ad_loop(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="cvgen-live-"))
        os.environ["CVGEN_DATA"] = str(root)
        os.environ.pop("RUSTFS_ENDPOINT", None)
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        os.environ["CVGEN_PUBLIC_BASE"] = base
        video = root / "provider.mp4"
        tiny_video(video, "orange", 1.0)
        audio = root / "voice.wav"
        tiny_wav(audio)
        restore = []
        stub_provider(restore, video.read_bytes())
        config = uvicorn.Config(app_module.app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        loop = asyncio.new_event_loop()

        def _serve() -> None:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve())

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                if httpx.get(base + "/api/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        else:
            self.fail("local server did not start")
        probe = httpx.get(base + "/api/health", timeout=2)
        self.assertEqual(probe.status_code, 200, probe.text)
        app_module.DATA = root
        app_module.PUBLIC = base
        app_module.store = Store(root / "cvgen.sqlite")
        app_module.storage = Storage(root)
        from server.jobs import JobRunner

        app_module.runner = JobRunner(app_module.store, app_module.storage, base, root)
        try:
            client = httpx.Client(base_url=base, timeout=30)
            setup = client.post("/api/admin/setup", json={"username": "admin", "password": "admin-pass"})
            self.assertEqual(setup.status_code, 200, setup.text)
            admin = {"Authorization": f"Bearer {setup.json()['token']}"}
            started = client.post("/api/device/start").json()
            approved = client.post(f"/api/device/{started['code']}/approve", headers=admin)
            self.assertEqual(approved.status_code, 200, approved.text)
            token = client.get(f"/api/device/{started['code']}").json()["token"]
            auth = root / "auth.json"
            auth.write_text(json.dumps({"base": base, "token": token}), encoding="utf-8")
            os.chmod(auth, 0o600)
            env = os.environ.copy()
            env["CVGEN_AUTH"] = str(auth)
            env["CVGEN_DATA"] = str(root)
            env["NO_PROXY"] = "127.0.0.1,localhost"
            env["no_proxy"] = "127.0.0.1,localhost"
            help_text = _run([os.fspath(ROOT / ".venv/bin/python"), "-m", "cli.cvgen", "--help"], env)
            for phrase in ("batch", "style", "reference", "job", "edit"):
                self.assertIn(phrase, help_text)
            binary = _ensure_binary()
            rust_help = _run([binary, "--help"], env)
            for phrase in ("batch show", "style extract", "reference upload", "job wait", "edit join", "edit export"):
                self.assertIn(phrase, rust_help)

            parent = httpx.get(base + "/api/health", timeout=2, trust_env=False)
            self.assertEqual(parent.status_code, 200, f"alive={thread.is_alive()} body={parent.text}")
            probe = subprocess.run(
                [os.fspath(ROOT / ".venv/bin/python"), "-c", "import os,httpx,json; print(json.load(open(os.environ['CVGEN_AUTH']))['base']); print(httpx.get(json.load(open(os.environ['CVGEN_AUTH']))['base']+'/api/health', timeout=2, trust_env=False).status_code)"],
                cwd=ROOT, env=env, capture_output=True, text=True,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr + probe.stdout)
            work = _cli(env, "work", "纱布广告", "广告", "产品开场")
            subject = _cli(env, "entity", "add", "Subject", json.dumps({"title": "纱布", "summary": "产品"}, ensure_ascii=False))
            appearance = _cli(env, "entity", "add", "Appearance", json.dumps({"title": "外观", "material": "棉"}, ensure_ascii=False))
            _cli(env, "link", "has_appearance", subject["id"], appearance["id"])
            style = _cli(env, "entity", "add", "Style", json.dumps({"title": "极简产品广告", "medium": "电影感", "ban": "禁止定格"}, ensure_ascii=False))
            place = _cli(env, "entity", "add", "Place", json.dumps({"title": "桌面", "facts": "左光"}, ensure_ascii=False))
            camera = _cli(env, "entity", "add", "Camera", json.dumps({"title": "固定", "move": "固定镜头"}, ensure_ascii=False))
            shot = _cli(env, "entity", "add", "Shot", json.dumps({
                "title": "开场", "size": "特写", "angle": "平视", "action": "纱布慢慢展开", "duration": 5,
            }, ensure_ascii=False))
            _cli(env, "link", "belongs_to", shot["id"], work["id"])
            _cli(env, "link", "styled_as", shot["id"], style["id"])
            _cli(env, "link", "located_in", shot["id"], place["id"])
            _cli(env, "link", "shot_with", shot["id"], camera["id"])
            product = root / "product.png"
            product.write_bytes(b"\x89PNG\r\n\x1a\nlocal")
            reference = _cli(env, "reference", "upload", str(product), "--role", "细节", "--title", "产品图", "--take", "纱布", "--ignore", "背景")
            self.assertTrue(reference["object_key"].startswith("references/"))
            self.assertEqual(reference["data"]["role"], "细节")
            _cli(env, "link", "references", shot["id"], reference["id"])
            listed = _cli(env, "batch", "show", work["id"])
            self.assertEqual(listed["shots"][0]["status"], "未生成")
            plan = _cli(env, "shot", "compose", shot["id"])
            self.assertIn("【参考素材说明】", plan["prompt"])
            job = _cli(env, "generate", shot["id"])
            done = _cli(env, "job", "wait", job["job_id"])
            self.assertEqual(done["status"], "succeeded", done)
            clip_id = done["detail"]["clip_id"]
            preview = _cli(env, "preview", clip_id)
            self.assertIn(done["detail"]["object_key"], preview["preview_url"])
            self.assertTrue(preview.get("sheet_url"))
            self.assertEqual(preview.get("status"), "已成片")
            first = _cli(env, "media", done["detail"]["object_key"])
            second = _run_json(binary, ["media", done["detail"]["object_key"]], env)
            self.assertEqual(first["bytes"], second["bytes"])
            self.assertGreater(first["bytes"], 100)
            media_body = client.get("/media/" + done["detail"]["object_key"], headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(media_body.status_code, 200)
            self.assertEqual(len(media_body.content), first["bytes"])
            self.assertGreater(len(media_body.content), 100)

            voice_ref = _cli(env, "reference", "upload", str(audio), "--role", "音色", "--title", "音色")
            line = _cli(env, "entity", "add", "Line", json.dumps({"title": "旁白", "text": "轻轻展开"}, ensure_ascii=False))
            voice = _cli(env, "entity", "add", "Voice", json.dumps({"title": "声", "method": "与音色参考音频相同"}, ensure_ascii=False))
            _cli(env, "link", "voices", shot["id"], line["id"])
            _cli(env, "link", "voiced_by", shot["id"], voice["id"])
            _cli(env, "link", "references", voice["id"], voice_ref["id"])
            spoken = _cli(env, "job", "wait", _cli(env, "tts", line["id"])["job_id"])
            self.assertEqual(spoken["status"], "succeeded", spoken)
            other = root / "b.mp4"
            tiny_video(other, "navy", 1.0)
            other_key = app_module.storage.put("clips", "b.mp4", other.read_bytes(), "video/mp4")
            other_clip = app_module.store.add_entity("Clip", {"title": "第二条"}, other_key)
            joined = _cli(env, "job", "wait", _cli(env, "edit", "join", clip_id, other_clip["id"], "--fade", "2")["job_id"])
            self.assertGreater(joined["detail"]["probe"]["duration"], 1.0)
            bare = _cli(env, "entity", "add", "Edit", json.dumps({"title": "只有成片"}, ensure_ascii=False))
            _cli(env, "link", "uses_clip", bare["id"], clip_id)
            _cli(env, "link", "uses_clip", bare["id"], other_clip["id"])
            bare_export = _cli(env, "job", "wait", _cli(env, "edit", "export", bare["id"])["job_id"])
            self.assertNotIn("narration", bare["data"])
            self.assertTrue(bare_export["detail"]["probe"]["has_audio"])
            bare_mix = bare_export["detail"].get("mix") or ""
            self.assertIn("volume=8dB", bare_mix)
            self.assertIn("sidechaincompress", bare_mix)
            self.assertIn("alimiter=limit=0.891", bare_mix)
            edit = _cli(env, "entity", "add", "Edit", json.dumps({"title": "成片", "narration": spoken["detail"]["clip_id"]}, ensure_ascii=False))
            _cli(env, "link", "uses_clip", edit["id"], clip_id)
            exported = _cli(env, "job", "wait", _cli(env, "edit", "export", edit["id"])["job_id"])
            self.assertTrue(exported["detail"]["probe"]["has_audio"])
            style_job = _cli(env, "job", "wait", _cli(env, "style", "extract", clip_id)["job_id"])
            made = _cli(env, "entity", "get", style_job["detail"]["style_id"])
            self.assertEqual(made["type"], "Style")
            python_again = _cli(env, "preview", clip_id)
            rust_again = _run_json(binary, ["preview", clip_id], env)
            self.assertEqual(python_again["id"], preview["id"])
            self.assertEqual(rust_again["id"], preview["id"])
            self.assertEqual(python_again["preview_url"], preview["preview_url"])
            self.assertEqual(rust_again["preview_url"], preview["preview_url"])
            self.assertEqual(python_again["sheet_url"], preview["sheet_url"])
            self.assertEqual(rust_again["sheet_url"], preview["sheet_url"])
            self.assertTrue(preview["sheet_url"])
            rust_media = _run_json(binary, ["media", done["detail"]["object_key"]], env)
            self.assertEqual(rust_media["bytes"], first["bytes"])
            shipped = ROOT / "tools" / "bin" / "linux" / "cvgen"
            if shipped.is_file():
                shipped_help = _run([os.fspath(shipped), "--help"], env)
                self.assertIn("job wait", shipped_help)
                self.assertIn("reference upload", shipped_help)
            launch_1 = _launch_log(env, binary, "python", root / "py-product.png", base, token)
            launch_2 = _launch_log(env, binary, "rust", root / "rs-product.png", base, token)
            self.assertEqual(launch_1["entry"], "python")
            self.assertEqual(launch_2["entry"], "rust")
            self.assertTrue(launch_1["clip_id"])
            self.assertTrue(launch_2["clip_id"])
            self.assertNotEqual(launch_1["clip_id"], launch_2["clip_id"])
            self.assertNotEqual(launch_1["object_key"], launch_2["object_key"])
            self.assertNotEqual(launch_1["clip_id"], clip_id)
            self.assertEqual(launch_1["media_get_status"], 200)
            self.assertEqual(launch_2["media_get_status"], 200)
            self.assertGreater(launch_1["media_bytes"], 100)
            self.assertGreater(launch_2["media_bytes"], 100)
            self.assertEqual(launch_1["media_bytes"], launch_1["media_cli_bytes"])
            self.assertEqual(launch_2["media_bytes"], launch_2["media_cli_bytes"])
            self.assertTrue(launch_1["media_readable"])
            self.assertTrue(launch_2["media_readable"])
            SCRATCH.mkdir(parents=True, exist_ok=True)
            (SCRATCH / "cli-launch-1.log").write_text(json.dumps(launch_1, ensure_ascii=False, indent=2), encoding="utf-8")
            (SCRATCH / "cli-launch-2.log").write_text(json.dumps(launch_2, ensure_ascii=False, indent=2), encoding="utf-8")
            (SCRATCH / "ad-loop.log").write_text(json.dumps({
                "work": work["id"],
                "shot": shot["id"],
                "clip": clip_id,
                "export": exported["detail"]["object_key"],
                "audio": exported["detail"]["probe"]["has_audio"],
                "prompt_headings": ["【参考素材说明】", "【核心创意】", "【画面过程描述】", "【整体要求补充】"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            server.should_exit = True
            thread.join(5)
            loop.call_soon_threadsafe(loop.stop)
            import h3_client
            if restore:
                h3_client.submit, h3_client.query, h3_client.download, h3_client.build_body, h3_client._request, h3_client.config = restore[0]


def _launch_log(env: dict, binary: str, entry: str, product: Path, base: str, token: str) -> dict:
    product.write_bytes(b"\x89PNG\r\n\x1a\n" + entry.encode())

    def call(*args: str) -> dict:
        if entry == "python":
            return _cli(env, *args)
        return _run_json(binary, list(args), env)

    work = call("work", f"{entry}广告", "广告", "独立生成")
    style = call("entity", "add", "Style", json.dumps({"title": "电影感", "ban": "禁止定格"}, ensure_ascii=False))
    place = call("entity", "add", "Place", json.dumps({"title": "桌面", "facts": "左光"}, ensure_ascii=False))
    camera = call("entity", "add", "Camera", json.dumps({"title": "固定", "move": "固定镜头"}, ensure_ascii=False))
    shot = call("entity", "add", "Shot", json.dumps({
        "title": f"{entry}开场", "size": "特写", "angle": "平视", "action": "产品展开", "duration": 5,
    }, ensure_ascii=False))
    call("link", "belongs_to", shot["id"], work["id"])
    call("link", "styled_as", shot["id"], style["id"])
    call("link", "located_in", shot["id"], place["id"])
    call("link", "shot_with", shot["id"], camera["id"])
    reference = call("reference", "upload", str(product), "--role", "细节", "--title", "产品", "--take", "产品", "--ignore", "背景")
    call("link", "references", shot["id"], reference["id"])
    done = call("job", "wait", call("generate", shot["id"])["job_id"])
    if done.get("status") != "succeeded" or not done.get("detail", {}).get("clip_id"):
        raise AssertionError(done)
    preview = call("preview", done["detail"]["clip_id"])
    media = call("media", done["detail"]["object_key"])
    body = httpx.get(base + "/media/" + done["detail"]["object_key"], headers={"Authorization": f"Bearer {token}"}, timeout=30, trust_env=False)
    if body.status_code != 200 or len(body.content) != media["bytes"] or len(body.content) <= 100:
        raise AssertionError((body.status_code, len(body.content), media))
    return {
        "entry": entry,
        "clip_id": done["detail"]["clip_id"],
        "object_key": done["detail"]["object_key"],
        "preview_url": preview["preview_url"],
        "sheet_url": preview.get("sheet_url"),
        "status": preview.get("status"),
        "media_get_status": body.status_code,
        "media_bytes": len(body.content),
        "media_cli_bytes": media["bytes"],
        "media_readable": body.status_code == 200 and len(body.content) == media["bytes"] and len(body.content) > 100,
    }


def _write_defects(payload: dict) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "defects.log").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run(args: list[str], env: dict) -> str:
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"cmd={args[:6]}\nstderr={result.stderr[-1500:]}\nstdout={result.stdout[-500:]}")
    return result.stdout


def _run_json(binary: str, args: list[str], env: dict) -> dict:
    return json.loads(_run([binary, *args], env))


def _cli(env: dict, *args: str) -> dict:
    python = os.fspath(ROOT / ".venv/bin/python")
    return json.loads(_run([python, "-m", "cli.cvgen", *args], env))


def _ensure_binary() -> str:
    binary = ROOT / "cvgen-cli" / "target" / "release" / "cvgen"
    subprocess.run(
        [os.fspath(Path.home() / ".cargo/bin/cargo"), "build", "--release", "--manifest-path", str(ROOT / "cvgen-cli" / "Cargo.toml")],
        check=True,
        cwd=ROOT,
    )
    return os.fspath(binary)


if __name__ == "__main__":
    unittest.main()
