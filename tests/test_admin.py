"""Admin login gates device approval, and only one cvgen stays online."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_integration import approve_device, boot


class AdminSeatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cvgen-admin-"))
        self.client = boot(self.root)
        os.environ.pop("CVGEN_ADMIN_PASSWORD", None)

    def test_setup_login_and_single_online_cvgen(self) -> None:
        short = self.client.post("/api/admin/setup", json={"username": "a", "password": "short"})
        self.assertEqual(short.status_code, 400)
        setup = self.client.post("/api/admin/setup", json={"username": "root", "password": "correct-horse"})
        self.assertEqual(setup.status_code, 200)
        again = self.client.post("/api/admin/setup", json={"username": "other", "password": "correct-horse"})
        self.assertEqual(again.status_code, 409)
        bad = self.client.post("/api/admin/login", json={"username": "root", "password": "wrong-pass"})
        self.assertEqual(bad.status_code, 401)
        logged = self.client.post("/api/admin/login", json={"username": "root", "password": "correct-horse"})
        self.assertEqual(logged.status_code, 200)
        headers = {"Authorization": f"Bearer {logged.json()['token']}"}
        self.assertEqual(self.client.get("/api/admin/session", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/status").json()["admin_ready"], True)
        locked = self.client.get("/api/view")
        self.assertEqual(locked.status_code, 401)
        self.assertNotIn("nodes", locked.json())
        opened = self.client.get("/api/view", headers=headers)
        self.assertEqual(opened.status_code, 200)
        self.assertIn("nodes", opened.json())
        self.assertEqual(self.client.get("/api/skills").status_code, 401)
        self.assertEqual(self.client.get("/api/skills", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/api/tools").status_code, 401)

        first = self.client.post("/api/device/start").json()
        denied = self.client.post(f"/api/device/{first['code']}/approve")
        self.assertEqual(denied.status_code, 401)
        approve_device(self.client, first["code"], headers)
        first_token = self.client.get(f"/api/device/{first['code']}").json()["token"]
        agent = {"Authorization": f"Bearer {first_token}"}
        self.assertEqual(self.client.get("/api/ontology", headers=agent).status_code, 200)

        second = self.client.post("/api/device/start").json()
        occupied = self.client.post(f"/api/device/{second['code']}/approve", headers=headers)
        self.assertEqual(occupied.status_code, 409)
        self.assertIn("已有一台", occupied.json()["detail"])
        self.assertEqual(self.client.get(f"/api/device/{second['code']}").json()["status"], "pending")

        listed = self.client.get("/api/admin/cvgen", headers=headers).json()
        online = [item for item in listed["items"] if item["online"]]
        self.assertEqual([item["code"] for item in online], [first["code"]])

        revoked = self.client.post(f"/api/admin/cvgen/{first['code']}/revoke", headers=headers)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(self.client.get("/api/ontology", headers=agent).status_code, 401)
        approve_device(self.client, second["code"], headers)
        second_token = self.client.get(f"/api/device/{second['code']}").json()["token"]
        self.assertEqual(
            self.client.get("/api/ontology", headers={"Authorization": f"Bearer {second_token}"}).status_code,
            200,
        )

    def test_stale_cvgen_frees_the_seat(self) -> None:
        setup = self.client.post("/api/admin/setup", json={"username": "root", "password": "correct-horse"})
        headers = {"Authorization": f"Bearer {setup.json()['token']}"}
        first = self.client.post("/api/device/start").json()
        approve_device(self.client, first["code"], headers)
        stale = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        import server.app as app_module
        app_module.store.save_device(first["code"], "approved", "kept-token", stale)
        second = self.client.post("/api/device/start").json()
        approved = self.client.post(f"/api/device/{second['code']}/approve", headers=headers)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(self.client.get("/api/ontology", headers={"Authorization": "Bearer kept-token"}).status_code, 401)

    def test_password_can_be_reset_from_session_or_recovery(self) -> None:
        setup = self.client.post("/api/admin/setup", json={"username": "root", "password": "correct-horse"})
        headers = {"Authorization": f"Bearer {setup.json()['token']}"}
        missing = self.client.post("/api/admin/reset", json={"recovery": "server-reset", "next_password": "brand-new-pass"})
        self.assertEqual(missing.status_code, 403)
        os.environ["CVGEN_ADMIN_PASSWORD"] = "server-reset"
        try:
            wrong = self.client.post("/api/admin/reset", json={"recovery": "wrong-reset", "next_password": "brand-new-pass"})
            self.assertEqual(wrong.status_code, 401)
            short = self.client.post("/api/admin/reset", json={"recovery": "server-reset", "next_password": "short"})
            self.assertEqual(short.status_code, 400)
            reset = self.client.post("/api/admin/reset", json={"recovery": "server-reset", "next_password": "brand-new-pass"})
            self.assertEqual(reset.status_code, 200)
            self.assertEqual(self.client.get("/api/admin/session", headers=headers).status_code, 401)
            old = self.client.post("/api/admin/login", json={"username": "root", "password": "correct-horse"})
            self.assertEqual(old.status_code, 401)
            logged = self.client.post("/api/admin/login", json={"username": "root", "password": "brand-new-pass"})
            self.assertEqual(logged.status_code, 200)
            fresh = {"Authorization": f"Bearer {logged.json()['token']}"}
            changed = self.client.post("/api/admin/password", headers=fresh, json={"password": "brand-new-pass", "next_password": "third-password"})
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(self.client.get("/api/admin/session", headers=fresh).status_code, 401)
            again = self.client.post("/api/admin/login", json={"username": "root", "password": "third-password"})
            self.assertEqual(again.status_code, 200)
        finally:
            os.environ.pop("CVGEN_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
