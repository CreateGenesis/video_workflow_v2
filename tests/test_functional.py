"""Functional path: stored clip is probed and sheeted by the hosted inspect job."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from server.jobs import JobRunner
from server.media import probe
from server.storage import Storage
from server.store import Store


def _color_clip(path: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[:300])


class InspectFunctionalTests(unittest.TestCase):
    def test_inspect_stores_probe_and_sheet(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="cvgen-inspect-"))
        store = Store(root / "state.sqlite")
        storage = Storage(root)
        clip_path = root / "sample.mp4"
        _color_clip(clip_path)
        measured = probe(clip_path)
        self.assertGreater(measured["duration"], 1)
        key = storage.put("clips", "sample.mp4", clip_path.read_bytes(), "video/mp4")
        clip = store.add_entity("Clip", {"title": "功能样片", "duration": 2}, key)
        runner = JobRunner(store, storage, "http://127.0.0.1:9", root)
        job = store.add_job("inspect", clip["id"], "running", {})
        detail = runner._inspect(job)
        self.assertGreater(detail["probe"]["duration"], 1)
        self.assertEqual(detail["probe"]["width"], 320)
        self.assertTrue(storage.get(detail["sheet_key"]).startswith(b"\xff\xd8"))
        observation = store.get_entity(detail["observation_id"])
        self.assertIn("duration", observation["data"]["summary"])

    def test_reconcile_writes_prompt_and_measured_duration(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="cvgen-reconcile-"))
        store = Store(root / "state.sqlite")
        storage = Storage(root)
        from tests.test_rules import build_shot

        shot_id = build_shot(store, duration=15)
        clip_path = root / "sample.mp4"
        _color_clip(clip_path)
        key = storage.put("clips", "kept.mp4", clip_path.read_bytes(), "video/mp4")
        clip = store.add_entity("Clip", {"title": shot_id, "duration": 0, "resolution": "768p横"}, key)
        job = store.add_job("generate", shot_id, "succeeded", {
            "submitted": True,
            "provider_task": "task-kept",
            "resolution": "768p横",
            "object_key": key,
            "clip_id": clip["id"],
            "prompt": "",
            "estimate_yuan": 0.0,
        })
        runner = JobRunner(store, storage, "http://127.0.0.1:9", root)
        detail = runner.reconcile_stored(job["id"])
        saved = store.get_job(job["id"])
        self.assertIn("【参考素材说明】", detail["prompt"])
        self.assertGreater(detail["duration"], 1)
        self.assertGreater(detail["estimate_yuan"], 0)
        self.assertEqual(saved["detail"]["prompt"], detail["prompt"])
        self.assertEqual(saved["detail"]["duration"], detail["duration"])
        self.assertEqual(store.get_entity(clip["id"])["data"]["duration"], detail["duration"])


if __name__ == "__main__":
    unittest.main()
