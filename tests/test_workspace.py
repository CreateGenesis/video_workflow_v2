"""Workspace ownership, catalog parity, retry, prompts, layout, and media proxy."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import server.app as app_module
from server.storage import Storage
from server.store import Store
from tests.test_capabilities import approve
from tests.test_integration import admin_headers


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


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="cvgen-space-"))
        self.client = boot(self.root)
        self.admin = admin_headers(self.client)
        self.agent = approve(self.client, self.admin)

    def test_existing_work_joins_first_workspace_and_selection_gates_actions(self) -> None:
        from server.scope import ensure_scope

        existing = app_module.store.add_entity("Work", {"title": "旧广告", "kind": "广告"})
        ensure_scope(app_module.store)
        listed = self.client.get("/api/workspaces", headers=self.admin)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(len(listed.json()["items"]), 1)
        workspace_id = listed.json()["items"][0]["id"]
        owners = [
            link for link in app_module.store.all_links()
            if link["name"] == "contains" and link["target_id"] == existing["id"]
        ]
        self.assertEqual(owners[0]["source_id"], workspace_id)
        second = self.client.post("/api/workspaces", headers=self.admin, json={"title": "另一组"})
        self.assertEqual(second.status_code, 200, second.text)
        used = self.client.post("/api/workspaces/use", headers=self.agent, json={"id": second.json()["id"]})
        self.assertEqual(used.status_code, 200, used.text)
        refused = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Shot",
            "data": {"title": "空镜头", "size": "中景", "angle": "平视", "action": "产品转出"},
        })
        self.assertEqual(refused.status_code, 400, refused.text)
        self.assertIn("先选择", refused.json()["detail"])
        work = self.client.post("/api/works", headers=self.agent, json={"title": "新产品", "kind": "广告"})
        self.assertEqual(work.status_code, 200, work.text)
        self.client.post("/api/works/use", headers=self.agent, json={"id": work.json()["id"]})
        shot = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Shot",
            "data": {"title": "开场", "size": "中景", "angle": "平视", "action": "产品转出"},
        })
        self.assertEqual(shot.status_code, 200, shot.text)
        self.client.post("/api/workspaces/use", headers=self.agent, json={"id": workspace_id})
        self.client.post("/api/works/use", headers=self.agent, json={"id": existing["id"]})
        other_style = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Style",
            "data": {"title": "另一作品风格", "medium": "电影"},
        })
        crossed = self.client.post("/api/link", headers=self.agent, json={
            "name": "styled_as",
            "source_id": shot.json()["id"],
            "target_id": other_style.json()["id"],
        })
        self.assertEqual(crossed.status_code, 400, crossed.text)
        self.assertIn("另一个作品", crossed.json()["detail"])
        scoped = self.client.get(f"/api/view?work_id={work.json()['id']}", headers=self.admin)
        ids = {node["id"] for node in scoped.json()["nodes"]}
        self.assertIn(shot.json()["id"], ids)
        self.assertNotIn(existing["id"], ids)
        self.assertNotIn(other_style.json()["id"], ids)

    def test_prompt_and_unowned_style_cannot_cross_works(self) -> None:
        first = self.client.post("/api/workspaces/use", headers=self.agent, json={"id": self.client.get("/api/workspaces", headers=self.admin).json()["items"][0]["id"]})
        self.assertEqual(first.status_code, 200, first.text)
        work_a = self.client.post("/api/works", headers=self.agent, json={"title": "甲", "kind": "广告"})
        self.assertEqual(work_a.status_code, 200, work_a.text)
        self.client.post("/api/works/use", headers=self.agent, json={"id": work_a.json()["id"]})
        shot_a = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Shot",
            "data": {"title": "甲镜头", "size": "中景", "angle": "平视", "action": "甲原来的动作"},
        })
        self.assertEqual(shot_a.status_code, 200, shot_a.text)
        style_a = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Style",
            "data": {"title": "甲风格", "medium": "电影"},
        })
        self.assertEqual(style_a.status_code, 200, style_a.text)
        work_b = self.client.post("/api/works", headers=self.agent, json={"title": "乙", "kind": "广告"})
        self.client.post("/api/works/use", headers=self.agent, json={"id": work_b.json()["id"]})
        shot_b = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Shot",
            "data": {"title": "乙镜头", "size": "中景", "angle": "平视", "action": "乙动作"},
        })
        self.assertEqual(shot_b.status_code, 200, shot_b.text)
        crossed_prompt = self.client.post(
            f"/api/shots/{shot_a.json()['id']}/prompt",
            headers=self.agent,
            json={"text": "乙改了甲"},
        )
        self.assertEqual(crossed_prompt.status_code, 400, crossed_prompt.text)
        self.assertIn("另一个作品", crossed_prompt.json()["detail"])
        kept = app_module.store.get_entity(shot_a.json()["id"])
        self.assertEqual(kept["data"]["action"], "甲原来的动作")
        crossed_show = self.client.get(f"/api/shots/{shot_a.json()['id']}/prompt", headers=self.agent)
        self.assertEqual(crossed_show.status_code, 400, crossed_show.text)
        crossed_restore = self.client.post(
            f"/api/shots/{shot_a.json()['id']}/prompt/restore",
            headers=self.agent,
            json={"index": 0},
        )
        self.assertEqual(crossed_restore.status_code, 400, crossed_restore.text)
        crossed_link = self.client.post("/api/link", headers=self.agent, json={
            "name": "styled_as",
            "source_id": shot_b.json()["id"],
            "target_id": style_a.json()["id"],
        })
        self.assertEqual(crossed_link.status_code, 400, crossed_link.text)
        self.assertIn("另一个作品", crossed_link.json()["detail"])
        self.assertFalse(any(
            link["source_id"] == shot_b.json()["id"] and link["target_id"] == style_a.json()["id"]
            for link in app_module.store.all_links()
        ))

    def test_jobs_against_another_work_are_refused(self) -> None:
        workspace = self.client.get("/api/workspaces", headers=self.admin).json()["items"][0]["id"]
        self.client.post("/api/workspaces/use", headers=self.agent, json={"id": workspace})
        work_a = self.client.post("/api/works", headers=self.agent, json={"title": "甲", "kind": "广告"}).json()
        self.client.post("/api/works/use", headers=self.agent, json={"id": work_a["id"]})
        shot_a = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Shot",
            "data": {"title": "甲镜头", "size": "中景", "angle": "平视", "action": "甲动作"},
        }).json()
        image = app_module.store.add_entity("Reference", {"title": "甲图", "role": "细节", "work_id": work_a["id"]}, "references/old.png")
        app_module.store.add_link("references", shot_a["id"], image["id"], "甲图")
        clip = app_module.store.add_entity("Clip", {"title": "甲片", "duration": 1, "work_id": work_a["id"]}, "clips/old.mp4")
        line = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Line",
            "data": {"title": "甲台词", "text": "甲说"},
        }).json()
        edit = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Edit",
            "data": {"title": "甲剪辑", "narration": "", "music": ""},
        }).json()
        failed = app_module.store.add_job("image", shot_a["id"], "failed", {"role": "细节", "error": "提交没有被接受"})
        work_b = self.client.post("/api/works", headers=self.agent, json={"title": "乙", "kind": "广告"}).json()
        self.client.post("/api/works/use", headers=self.agent, json={"id": work_b["id"]})
        before = len(app_module.store.list_jobs())
        calls = [
            ("/api/generate", {"shot_id": shot_a["id"], "resolution": "768p横"}),
            ("/api/image", {"target_id": shot_a["id"], "detail": {"role": "细节"}}),
            (f"/api/images/{image['id']}/redraw", {}),
            ("/api/tts", {"target_id": line["id"]}),
            ("/api/frame", {"target_id": clip["id"], "detail": {"at": "first", "role": "首帧"}}),
            ("/api/check", {"target_id": clip["id"]}),
            ("/api/edit", {"target_id": edit["id"], "detail": {"op": "export", "clips": [clip["id"]]}}),
            ("/api/inspect", {"target_id": clip["id"]}),
            ("/api/style", {"target_id": clip["id"]}),
        ]
        for path, payload in calls:
            response = self.client.post(path, headers=self.agent, json=payload)
            self.assertEqual(response.status_code, 400, f"{path} {response.text}")
            self.assertIn("另一个作品", response.json()["detail"])
        retried = self.client.post(f"/api/jobs/{failed['id']}/retry", headers=self.admin)
        self.assertEqual(retried.status_code, 400, retried.text)
        self.assertIn("另一个作品", retried.json()["detail"])
        compose = self.client.get(f"/api/shot/{shot_a['id']}/compose", headers=self.agent)
        self.assertEqual(compose.status_code, 400, compose.text)
        self.assertIn("另一个作品", compose.json()["detail"])
        self.assertEqual(len(app_module.store.list_jobs()), before)
        self.assertEqual(app_module.store.get_entity(image["id"])["object_key"], "references/old.png")

    def test_retry_prompt_redraw_and_layout_share_one_catalog(self) -> None:
        catalog = self.client.get("/api/cli", headers=self.agent)
        names = {item["name"] for item in catalog.json()["commands"]}
        for name in ("workspace use", "work use", "retry", "prompt save", "prompt restore", "redraw", "layout save", "layout tidy"):
            self.assertIn(name, names)
        self.assertTrue(all("method" in item and "path" in item for item in catalog.json()["commands"]))
        workspace = self.client.get("/api/workspaces", headers=self.admin).json()["items"][0]["id"]
        self.client.post("/api/workspaces/use", headers=self.agent, json={"id": workspace})
        work = self.client.post("/api/works", headers=self.agent, json={"title": "抽卡", "kind": "广告"}).json()
        self.client.post("/api/works/use", headers=self.agent, json={"id": work["id"]})
        shot = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Shot",
            "data": {"title": "产品", "size": "特写", "angle": "平视", "action": "第一版动作"},
        }).json()
        saved = self.client.post(f"/api/shots/{shot['id']}/prompt", headers=self.admin, json={"text": "第二版动作"})
        self.assertEqual(saved.status_code, 200, saved.text)
        restored = self.client.post(f"/api/shots/{shot['id']}/prompt/restore", headers=self.admin, json={"index": 0})
        versions = restored.json()["versions"]
        self.assertEqual(len(versions), 3)
        self.assertEqual(versions[-1]["text"], versions[0]["text"])
        self.assertNotIn("v1", json.dumps(versions))
        other = self.client.post("/api/entity", headers=self.agent, json={
            "type": "Shot",
            "data": {"title": "可重试", "size": "中景", "angle": "平视", "action": "再来一次"},
        }).json()
        failed = app_module.store.add_job("image", shot["id"], "failed", {"role": "细节", "error": "提交没有被接受"})
        unknown = app_module.store.add_job("generate", other["id"], "unknown", {"error": "提交不明", "resolution": "768p横"})
        held = app_module.store.add_job("image", shot["id"], "unknown", {"provider_task": "upstream-1", "submitted": True})
        done = app_module.store.add_job("image", shot["id"], "succeeded", {})
        queued = app_module.store.add_job("image", shot["id"], "queued", {})
        self.assertEqual(self.client.post(f"/api/jobs/{done['id']}/retry", headers=self.admin).status_code, 409)
        self.assertEqual(self.client.post(f"/api/jobs/{held['id']}/retry", headers=self.admin).status_code, 409)
        self.assertEqual(self.client.post(f"/api/jobs/{queued['id']}/retry", headers=self.admin).status_code, 409)
        calls = []

        def fake_provider(_runner, url, key, body):
            calls.append((url, body))
            return 200, {"data": [{"b64_json": "iVBORw0KGgo="}]}, b""

        import server.jobs as jobs_module
        original = jobs_module.JobRunner._provider_json
        jobs_module.JobRunner._provider_json = fake_provider
        self.addCleanup(lambda: setattr(jobs_module.JobRunner, "_provider_json", original))
        retried = self.client.post(f"/api/jobs/{failed['id']}/retry", headers=self.admin)
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertNotEqual(retried.json()["job_id"], failed["id"])
        released = self.client.post(f"/api/jobs/{unknown['id']}/retry", headers=self.agent)
        self.assertEqual(released.status_code, 200, released.text)
        self.assertNotEqual(released.json()["job_id"], unknown["id"])
        self.client.post("/api/settings/providers", headers=self.admin, json={
            "capability": "image", "base": "http://image.test", "key": "image-key",
        })
        self.client.post("/api/provider/model", headers=self.admin, json={"capability": "image", "source": "image-flow"})
        image = app_module.store.add_entity("Reference", {"title": "旧图", "role": "细节"}, "references/old.png")
        app_module.storage.put("references", "old.png", b"\x89PNG\r\n\x1a\nold", "image/png")
        app_module.store.add_link("references", shot["id"], image["id"], "已生成")
        redraw = self.client.post(f"/api/images/{image['id']}/redraw", headers=self.admin)
        self.assertEqual(redraw.status_code, 200, redraw.text)
        self.assertEqual(redraw.json()["kept"], "references/old.png")
        import sqlite3
        import time
        time.sleep(0.4)
        own = sqlite3.connect(self.root / "cvgen.sqlite")
        kept = own.execute("select object_key from entities where id=?", (image["id"],)).fetchone()[0]
        own.close()
        self.assertEqual(kept, "references/old.png")
        self.assertEqual(len([item for item in calls if (item[1] or {}).get("model")]), 1)
        tidy = self.client.post("/api/layout/tidy", headers=self.admin)
        self.assertEqual(tidy.status_code, 200, tidy.text)
        before = app_module.store.all_links()
        moved = self.client.post("/api/layout", headers=self.admin, json={"positions": {shot["id"]: {"x": 40, "y": 80}}})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(app_module.store.all_links(), before)
        shown = self.client.get(f"/api/view?work_id={work['id']}", headers=self.admin).json()
        node = next(item for item in shown["nodes"] if item["id"] == shot["id"])
        self.assertEqual(node["position"], {"x": 40, "y": 80})


class ProxyTests(unittest.TestCase):
    def test_proxy_uses_socks_only_after_direct_failure_and_rejects_intranet(self) -> None:
        from server.proxy import fetch, public_target

        seen = []

        class Direct:
            def open(self, request, timeout=20):
                seen.append("direct")
                raise OSError("direct down")

        class Socks:
            def open(self, request, timeout=20):
                seen.append("socks")
                return io.BytesIO(b"\x89PNG\r\n\x1a\nproxied")

        class Headered(io.BytesIO):
            headers = {"Content-Type": "image/png"}

        Socks.open = lambda self, request, timeout=20: (_ for _ in ()).throw(None) if False else Headered(b"\x89PNG")
        # The lambda above is hard to read; use a real opener below.
        class Body:
            headers = {"Content-Type": "image/png"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"\x89PNG\r\n\x1a\nproxied"

        class SocksOpener:
            def open(self, request, timeout=20):
                seen.append("socks")
                return Body()

        payload, content_type = fetch("https://example.com/card.png", opener=Direct(), socks_opener=SocksOpener())
        self.assertEqual(seen, ["direct", "socks"])
        self.assertTrue(payload.startswith(b"\x89PNG"))
        self.assertEqual(content_type, "image/png")
        with self.assertRaises(ValueError):
            public_target("http://127.0.0.1/secret.png")
        with self.assertRaises(ValueError):
            public_target("http://192.168.1.8/secret.png")
        with self.assertRaises(ValueError):
            fetch("https://example.com/page.html", opener=Html(), socks_opener=None)

    def test_logged_in_proxy_returns_same_origin_and_hides_credential(self) -> None:
        import socket
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        root = Path(tempfile.mkdtemp(prefix="cvgen-proxy-"))
        client = boot(root)
        admin = admin_headers(client)
        secret = "socks-user:socks-pass"
        image = b"\x89PNG\r\n\x1a\nremote"
        seen = []

        class ImageHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                seen.append(("http", self.path))
                body = image
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        class HtmlHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                body = b"<html>not media</html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        image_server = ThreadingHTTPServer(("127.0.0.1", 0), ImageHandler)
        html_server = ThreadingHTTPServer(("127.0.0.1", 0), HtmlHandler)
        threading.Thread(target=image_server.serve_forever, daemon=True).start()
        threading.Thread(target=html_server.serve_forever, daemon=True).start()
        self.addCleanup(image_server.shutdown)
        self.addCleanup(html_server.shutdown)
        image_port = image_server.server_address[1]
        html_port = html_server.server_address[1]

        def serve_socks(listener: socket.socket) -> None:
            while True:
                try:
                    conn, _addr = listener.accept()
                except OSError:
                    return
                threading.Thread(target=handle_socks, args=(conn,), daemon=True).start()

        def handle_socks(conn: socket.socket) -> None:
            try:
                hello = _recv_exact(conn, 2)
                methods = _recv_exact(conn, hello[1])
                if 2 not in methods:
                    conn.sendall(b"\x05\xff")
                    return
                conn.sendall(b"\x05\x02")
                _recv_exact(conn, 1)
                user_len = _recv_exact(conn, 1)[0]
                user = _recv_exact(conn, user_len).decode()
                pass_len = _recv_exact(conn, 1)[0]
                password = _recv_exact(conn, pass_len).decode()
                seen.append(("auth", f"{user}:{password}"))
                if f"{user}:{password}" != secret:
                    conn.sendall(b"\x01\x01")
                    return
                conn.sendall(b"\x01\x00")
                header = _recv_exact(conn, 4)
                if header[1] != 1 or header[3] != 3:
                    conn.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                    return
                host_len = _recv_exact(conn, 1)[0]
                host = _recv_exact(conn, host_len).decode()
                port = int.from_bytes(_recv_exact(conn, 2), "big")
                seen.append(("socks", host, port))
                upstream = socket.create_connection(("127.0.0.1", image_port if host == "images.example" else html_port), timeout=5)
                conn.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                relay(conn, upstream)
            except Exception:
                return
            finally:
                conn.close()

        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        threading.Thread(target=serve_socks, args=(listener,), daemon=True).start()
        self.addCleanup(listener.close)
        socks_port = listener.getsockname()[1]
        os.environ["CVGEN_SOCKS5"] = f"socks5://{secret}@127.0.0.1:{socks_port}"
        self.addCleanup(lambda: os.environ.pop("CVGEN_SOCKS5", None))

        def _recv_exact(conn: socket.socket, count: int) -> bytes:
            data = b""
            while len(data) < count:
                chunk = conn.recv(count - len(data))
                if not chunk:
                    raise OSError("socks closed")
                data += chunk
            return data

        def relay(left: socket.socket, right: socket.socket) -> None:
            import select
            pair = [left, right]
            left.settimeout(2)
            right.settimeout(2)
            while True:
                ready, _, _ = select.select(pair, [], [], 2)
                if not ready:
                    break
                for source in ready:
                    target = right if source is left else left
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    target.sendall(chunk)

        import server.proxy as proxy_module

        real_getaddrinfo = socket.getaddrinfo

        def stand_in_dns(host, port, *args, **kwargs):
            if host == "images.example":
                return real_getaddrinfo("example.com", port, *args, **kwargs)
            return real_getaddrinfo(host, port, *args, **kwargs)

        proxy_module.socket.getaddrinfo = stand_in_dns
        self.addCleanup(lambda: setattr(proxy_module.socket, "getaddrinfo", real_getaddrinfo))
        real_create = socket.create_connection

        def direct_fails(address, timeout=None, source_address=None):
            host = address[0]
            if host == "images.example":
                seen.append(("direct", host))
                raise OSError("direct down")
            return real_create(address, timeout, source_address)

        socket.create_connection = direct_fails
        self.addCleanup(lambda: setattr(socket, "create_connection", real_create))

        from server.scope import ensure_scope

        ensure_scope(app_module.store)
        workspace_id = app_module.store.list_entities("Workspace")[0]["id"]
        app_module.store.set_setting("selected_workspace", workspace_id)
        work = app_module.store.add_entity("Work", {"title": "代理作品", "kind": "广告"})
        app_module.store.add_link("contains", workspace_id, work["id"], "")
        app_module.store.set_setting("selected_work", work["id"])
        shot = app_module.store.add_entity("Shot", {"title": "镜头", "size": "中景", "angle": "平视", "action": "转出"})
        app_module.store.add_link("belongs_to", shot["id"], work["id"], "")
        reference = app_module.store.add_entity(
            "Reference",
            {"title": "远图", "role": "主体"},
            object_key="http://images.example/card.png",
        )
        app_module.store.add_link("references", shot["id"], reference["id"], "")

        view = client.get("/api/view", params={"work_id": work["id"]}, headers=admin)
        self.assertEqual(view.status_code, 200, view.text)
        node = next(item for item in view.json()["nodes"] if item["id"] == reference["id"])
        site = node["preview_url"]
        self.assertTrue(site.startswith("http://127.0.0.1:9/api/media/proxy/"), site)
        self.assertNotIn(secret, site)
        self.assertNotIn(secret, json.dumps(view.json()))
        self.assertIn(("direct", "images.example"), seen)
        self.assertIn(("socks", "images.example", 80), seen)
        token = site.rsplit("/", 1)[-1]
        locked = client.get(f"/api/media/proxy/{token}")
        self.assertEqual(locked.status_code, 401)
        opened = client.get(f"/api/media/proxy/{token}", headers=admin)
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertEqual(opened.content, image)
        self.assertNotIn(secret, opened.text)
        self.assertNotIn(secret, json.dumps(app_module.store.recent()))
        with self.assertRaises(ValueError):
            proxy_module.fetch("http://127.0.0.1/secret.png")
        with self.assertRaises(ValueError):
            proxy_module.fetch("http://192.168.1.8/secret.png")
        with self.assertRaises(ValueError):
            proxy_module.fetch("http://example.com/page.html")
        archive_text = _archive_text()
        self.assertNotIn(secret, archive_text)
        self.assertNotIn("egress43", archive_text)


class Html:
    def open(self, request, timeout=20):
        class Body:
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"<html></html>"

        return Body()


def _archive_text() -> str:
    root = Path(__file__).resolve().parents[1] / "tools" / "dist"
    chunks = []
    for path in sorted(root.glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            chunks.append(" ".join(archive.namelist()))
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                chunks.append(archive.read(name).decode("utf-8", "replace"))
    return "\n".join(chunks)


if __name__ == "__main__":
    unittest.main()
