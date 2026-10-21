"""Drive shipped rules, compose, storage, and hosted job guards."""

from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path

from server.compose import HEADINGS, compose
from server.jobs import JobRunner
from server.media import passthrough
from server.rules import can_generate, passthrough_allowed, provider_outcome, shell_forbidden, shot_status
from server.storage import Storage
from server.store import Store


def isolated(name: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix=f"cvgen-{name}-"))
    return root


def build_shot(store: Store, *, role: str = "细节", duration: int = 5, size: str = "特写") -> str:
    place = store.add_entity("Place", {"title": "雪原", "facts": "左白桦，右雪坡"})
    detail = store.add_entity("Detail", {"title": "纱布卷", "material": "白棉纱"})
    style = store.add_entity("Style", {"title": "电影", "medium": "Q版三维", "ban": "禁止定格"})
    camera = store.add_entity("Camera", {"title": "固定", "move": "固定镜头"})
    ref = store.add_entity(
        "Reference",
        {"title": "纱布", "role": role, "take": "纱布卷法", "ignore": "背景"},
        "references/gauze.png",
    )
    shot = store.add_entity("Shot", {
        "title": "缠纱布",
        "size": size,
        "angle": "平视",
        "action": "双手把白纱布绕两圈",
        "duration": duration,
    })
    for name, target in (
        ("located_in", place),
        ("holds", detail),
        ("styled_as", style),
        ("shot_with", camera),
        ("references", ref),
    ):
        store.add_link(name, shot["id"], target["id"])
    return shot["id"]


class RuleTests(unittest.TestCase):
    def test_generate_blocks_open_unknown_and_succeeded(self) -> None:
        for status in ("queued", "running", "unknown", "succeeded"):
            allowed, reason = can_generate([{"status": status, "kind": "generate"}])
            self.assertFalse(allowed, status)
            self.assertIn("不能再次提交", reason)
        allowed, reason = can_generate([{"status": "failed", "kind": "generate"}])
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_shot_status_labels(self) -> None:
        self.assertEqual(shot_status([]), "未生成")
        self.assertEqual(shot_status([{"kind": "generate", "status": "failed"}]), "失败")
        self.assertEqual(shot_status([{"kind": "generate", "status": "unknown"}]), "提交不明")
        self.assertEqual(shot_status([{"kind": "generate", "status": "running"}]), "排队")
        self.assertEqual(shot_status([
            {"kind": "generate", "status": "failed"},
            {"kind": "generate", "status": "succeeded"},
        ]), "已成片")

    def test_passthrough_stays_closed_and_rejects_shell(self) -> None:
        self.assertFalse(passthrough_allowed("0"))
        self.assertFalse(passthrough_allowed(""))
        self.assertTrue(passthrough_allowed("1"))
        self.assertTrue(shell_forbidden(["-i", "a;rm"]))
        self.assertFalse(shell_forbidden(["-i", "clip.mp4"]))

    def test_provider_outcome(self) -> None:
        self.assertEqual(provider_outcome({"status": "SUCCESS", "video_url": "https://x"}), "ready")
        self.assertEqual(provider_outcome({"status": "failed"}), "failed")
        self.assertEqual(provider_outcome({"status": "QUEUED"}), "pending")
        self.assertEqual(provider_outcome({"status": "weird"}), "unknown")


class ComposeTests(unittest.TestCase):
    def test_compose_has_four_headings_and_rejects_bad_input(self) -> None:
        store = Store(isolated("compose") / "state.sqlite")
        shot_id = build_shot(store)
        plan = compose(store, shot_id)
        for heading in HEADINGS:
            self.assertIn(heading, plan["prompt"])
        self.assertTrue(plan["can_submit"])
        self.assertIn("24 帧顺滑", plan["prompt"])
        with self.assertRaises(ValueError):
            compose(store, shot_id, "2K")
        store2 = Store(isolated("compose-empty") / "state.sqlite")
        empty = store2.add_entity("Shot", {
            "title": "空",
            "size": "中景",
            "angle": "平视",
            "action": "走路",
            "duration": 5,
        })
        empty_plan = compose(store2, empty["id"])
        self.assertFalse(empty_plan["can_submit"])
        self.assertTrue(any("不能提交" in item for item in empty_plan["warnings"]))


class StorageTests(unittest.TestCase):
    def test_local_put_get_roundtrip(self) -> None:
        root = isolated("storage")
        os.environ.pop("RUSTFS_ENDPOINT", None)
        storage = Storage(root)
        key = storage.put("references", "gauze.png", b"png-bytes", "image/png")
        self.assertEqual(storage.get(key), b"png-bytes")
        self.assertIn("/media/references/gauze.png", storage.signed_url(key, "http://127.0.0.1:9"))
        with self.assertRaises(ValueError):
            storage.put("references", "../secret", b"no")


class JobGuardTests(unittest.TestCase):
    def test_second_generate_is_refused_without_provider_call(self) -> None:
        root = isolated("dedup")
        store = Store(root / "state.sqlite")
        shot_id = build_shot(store)
        store.add_job("generate", shot_id, "unknown", {"submitted": True})
        runner = JobRunner(store, Storage(root), "http://127.0.0.1:9", root)
        with self.assertRaises(RuntimeError) as caught:
            runner.start("generate", shot_id, {})
        self.assertIn("不能再次提交", str(caught.exception))
        self.assertEqual(len(store.jobs_for(shot_id, "generate")), 1)

    def test_closed_passthrough_does_not_run_ffmpeg(self) -> None:
        root = isolated("pass")
        store = Store(root / "state.sqlite")
        called = []

        def fake_pass(*args, **kwargs):
            called.append(args)
            return {"code": 0}

        runner = JobRunner(store, Storage(root), "http://127.0.0.1:9", root)
        job = store.add_job("ffmpeg", None, "queued", {"args": ["-version"]})
        import server.media as media_module
        original = media_module.passthrough
        media_module.passthrough = fake_pass
        try:
            with self.assertRaises(RuntimeError):
                runner._ffmpeg(job)
        finally:
            media_module.passthrough = original
        self.assertEqual(called, [])
        self.assertEqual(store.setting("ffmpeg_passthrough", "0"), "0")
        with self.assertRaises(Exception):
            passthrough(["-filter", "a;rm -rf"], Path("."))

    def test_learn_stores_reference_and_observation(self) -> None:
        root = isolated("learn")
        store = Store(root / "state.sqlite")
        storage = Storage(root)
        runner = JobRunner(store, storage, "http://127.0.0.1:9", root)

        class Response:
            headers = type("H", (), {"get_content_type": staticmethod(lambda: "image/png")})()

            def read(self):
                return b"image-bytes"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        import server.jobs as jobs_module
        original = jobs_module.urllib.request.urlopen
        jobs_module.urllib.request.urlopen = lambda *args, **kwargs: Response()
        try:
            job = store.add_job("learn", None, "running", {"url": "https://example.test/ref.png", "role": "风格"})
            detail = runner._learn(job)
        finally:
            jobs_module.urllib.request.urlopen = original
        entity = store.get_entity(detail["entity_id"])
        self.assertEqual(storage.get(entity["object_key"]), b"image-bytes")
        observation = store.get_entity(detail["observation_id"])
        self.assertIn("入库", observation["data"]["summary"])

    def test_tts_stores_audio_from_provider_result(self) -> None:
        root = isolated("tts")
        store = Store(root / "state.sqlite")
        storage = Storage(root)
        storage.put("references", "voice.wav", b"voice-bytes", "audio/wav")
        shot = store.add_entity("Shot", {"title": "旁白镜", "size": "中景", "angle": "平视", "action": "说话", "duration": 5})
        line = store.add_entity("Line", {"title": "一句", "text": "你好"})
        voice = store.add_entity("Voice", {"title": "音色", "method": "与音色参考音频相同"})
        ref = store.add_entity("Reference", {"title": "音色样", "role": "音色"}, "references/voice.wav")
        store.add_link("voices", shot["id"], line["id"])
        store.add_link("voiced_by", shot["id"], voice["id"])
        store.add_link("references", voice["id"], ref["id"])
        runner = JobRunner(store, storage, "http://127.0.0.1:9", root)
        calls = []

        def fake_request(url, token, body=None, timeout=120):
            calls.append(body["prompt_simple"][:30])
            return 200, {"data": {"task_id": "tts-task"}}

        def fake_query(task_id):
            return {"status": "SUCCESS", "video_url": "https://provider.test/out.wav"}

        def fake_download(url, dest):
            Path(dest).write_bytes(b"spoken-audio")
            return Path(dest)

        import h3_client
        original = (h3_client._request, h3_client.query, h3_client.download, h3_client.config)
        h3_client._request = fake_request
        h3_client.query = fake_query
        h3_client.download = fake_download
        h3_client.config = lambda: {"base": "https://example.test", "token": "t", "workflow": "indextts2-v1"}
        try:
            job = store.add_job("tts", line["id"], "running", {})
            detail = runner._tts(job)
        finally:
            h3_client._request, h3_client.query, h3_client.download, h3_client.config = original
        self.assertTrue(calls[0].startswith("data:audio/wav;base64,"))
        clip = store.get_entity(detail["clip_id"])
        self.assertEqual(storage.get(clip["object_key"]), b"spoken-audio")

    def test_concurrent_generate_allows_only_one(self) -> None:
        root = isolated("race")
        store = Store(root / "state.sqlite")
        shot_id = build_shot(store)
        runner = JobRunner(store, Storage(root), "http://127.0.0.1:9", root)
        gate = threading.Barrier(2)
        results = []

        def attempt() -> None:
            gate.wait()
            try:
                results.append(runner.start("generate", shot_id, {"force": True}))
            except RuntimeError as exc:
                results.append(str(exc))

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        started = [item for item in results if isinstance(item, dict)]
        refused = [item for item in results if isinstance(item, str)]
        self.assertEqual(len(started), 1)
        self.assertEqual(len(refused), 1)
        self.assertIn("不能再次提交", refused[0])

    def test_resume_waits_on_existing_provider_task(self) -> None:
        root = isolated("resume")
        store = Store(root / "state.sqlite")
        storage = Storage(root)
        shot_id = build_shot(store)
        store.add_job("generate", shot_id, "running", {"submitted": True, "provider_task": "task-kept", "resolution": "768p横"})
        runner = JobRunner(store, storage, "http://127.0.0.1:9", root)
        seen = []

        def fake_query(task_id):
            seen.append(task_id)
            return {"status": "SUCCESS", "video_url": "https://provider.test/clip.mp4"}

        def fake_download(url, dest):
            Path(dest).write_bytes(b"\x00\x00\x00\x18ftypmp42clip")
            return Path(dest)

        import h3_client
        import server.jobs as jobs_module
        original = (h3_client.query, h3_client.download, jobs_module.contact_sheet, jobs_module.probe, jobs_module.frame_at)
        h3_client.query = fake_query
        h3_client.download = fake_download
        jobs_module.contact_sheet = lambda src, dest: dest.write_bytes(b"sheet")
        jobs_module.probe = lambda path: {"duration": 15.0, "width": 768, "height": 432, "fps": "24/1", "codec": "h264"}
        jobs_module.frame_at = lambda src, dest, second: dest.write_bytes(b"frame")
        try:
            resumed = runner.resume_open()
            self.assertEqual(len(resumed), 1)
            worker = next(thread for thread in threading.enumerate() if thread.name == f"cvgen-{resumed[0]}")
            worker.join(3)
        finally:
            h3_client.query, h3_client.download, jobs_module.contact_sheet, jobs_module.probe, jobs_module.frame_at = original
        job = store.get_job(resumed[0])
        self.assertEqual(job["detail"].get("error", ""), "")
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(seen, ["task-kept"])
        self.assertEqual(storage.get(job["detail"]["object_key"])[:8], b"\x00\x00\x00\x18ftyp")
        self.assertIn("【参考素材说明】", job["detail"]["prompt"])
        self.assertEqual(job["detail"]["duration"], 15.0)
        self.assertEqual(job["detail"]["estimate_yuan"], 7.5)
        clip = store.get_entity(job["detail"]["clip_id"])
        self.assertEqual(clip["data"]["duration"], 15.0)


if __name__ == "__main__":
    unittest.main()
