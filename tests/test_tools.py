"""The site serves three native cvgen binaries."""

from __future__ import annotations

import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import server.app as app_module
from tools.build_release import package


class ToolPackageTests(unittest.TestCase):
    def test_three_packages_are_native_binaries(self) -> None:
        out = Path(tempfile.mkdtemp(prefix="cvgen-tools-"))
        binaries = {
            "linux": out / "linux-cvgen",
            "macos": out / "macos-cvgen",
            "windows": out / "cvgen.exe",
        }
        binaries["linux"].write_bytes(b"\x7fELF" + b"linux-binary")
        binaries["macos"].write_bytes(b"\xcf\xfa\xed\xfe" + b"macos-binary")
        binaries["windows"].write_bytes(b"MZ" + b"windows-binary")
        written = package(out, binaries)
        self.assertEqual(len(written), 3)
        original = app_module.RELEASES
        app_module.RELEASES = out
        root = Path(tempfile.mkdtemp(prefix="cvgen-tools-data-"))
        os.environ["CVGEN_DATA"] = str(root)
        app_module.DATA = root
        from server.store import Store

        app_module.store = Store(root / "cvgen.sqlite")
        try:
            client = TestClient(app_module.app)
            setup = client.post("/api/admin/setup", json={"username": "tools", "password": "admin-pass"})
            self.assertEqual(setup.status_code, 200)
            headers = {"Authorization": f"Bearer {setup.json()['token']}"}
            self.assertEqual(client.get("/api/tools").status_code, 401)
            listed = client.get("/api/tools", headers=headers)
            self.assertEqual(listed.status_code, 200)
            items = {item["platform"]: item for item in listed.json()["items"]}
            self.assertEqual(set(items), {"linux", "macos", "windows"})
            for platform, item in items.items():
                downloaded = client.get(item["url"], headers=headers)
                self.assertEqual(downloaded.status_code, 200, platform)
                with zipfile.ZipFile(out / item["filename"]) as archive:
                    names = set(archive.namelist())
                    note = archive.read("使用说明.txt").decode("utf-8")
                    index = archive.read("skills/cvgen-index.md").decode("utf-8")
                self.assertNotIn("cvgen.cmd", names)
                self.assertNotIn("cvgen.ps1", names)
                self.assertNotIn("requirements-cli.txt", names)
                self.assertFalse(any(name.endswith(".whl") for name in names))
                self.assertIn("skills/", names)
                self.assertIn("skills/cvgen-index.md", names)
                self.assertIn("cvgen skill show", note)
                self.assertIn("cvgen skill show", index)
                self.assertNotIn("http://", index)
                self.assertNotIn("https://", index)
                self.assertNotIn("setup", note)
                if platform == "windows":
                    self.assertIn("cvgen.exe", names)
                    self.assertTrue(archive_bytes(out / item["filename"], "cvgen.exe").startswith(b"MZ"))
                else:
                    self.assertIn("cvgen", names)
                    payload = archive_bytes(out / item["filename"], "cvgen")
                    if platform == "linux":
                        self.assertTrue(payload.startswith(b"\x7fELF"))
                    else:
                        self.assertTrue(payload.startswith(b"\xcf\xfa\xed\xfe"))
        finally:
            app_module.RELEASES = original


def archive_bytes(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


if __name__ == "__main__":
    unittest.main()
