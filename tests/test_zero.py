"""Functional checks for the Zero story seed and composed prompt."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.compose import HEADINGS, compose
from server.storage import Storage
from server.store import Store
from server.stories import seed_zero_carry


class ZeroStoryTests(unittest.TestCase):
    def test_seed_composes_fifteen_second_detail_shot(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="cvgen-zero-"))
        store = Store(root / "state.sqlite")
        seeded = seed_zero_carry(store)
        plan = compose(store, seeded["shot_id"], "768p横")
        for heading in HEADINGS:
            self.assertIn(heading, plan["prompt"])
        self.assertEqual(plan["duration"], 15)
        self.assertEqual(plan["prompt"].count("正向："), 3)
        self.assertIn("白纱布绕两圈", plan["prompt"])
        self.assertIn("动作从下文重新开始", plan["prompt"])
        self.assertTrue(any(ref["role"] == "细节" for ref in plan["references"]))
        self.assertNotIn("0～", plan["prompt"])
        self.assertNotIn("定格动画", plan["prompt"])
        self.assertTrue(plan["can_submit"])

    def test_bundled_references_are_pngs(self) -> None:
        from assets.make_zero_refs import write

        root = Path(tempfile.mkdtemp(prefix="cvgen-refs-"))
        write(root)
        storage = Storage(root)
        for name in ("zero-space.png", "zero-gauze.png"):
            data = (root / "references" / name).read_bytes()
            self.assertTrue(data.startswith(b"\x89PNG"))
            key = storage.put("references", name, data, "image/png")
            self.assertEqual(storage.get(key)[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
