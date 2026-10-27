"""One path: image deps, both processes, CLI catalog, hosted products page."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def _text(path: str) -> str:
    return (ROOT / path).read_text()


def test_images_split_deps_and_compose_starts_both_packages():
    platform_reqs = _text("requirements-platform.txt")
    agent_reqs = _text("requirements-agent.txt")
    assert "agno" not in platform_reqs
    assert "mcp" not in platform_reqs
    assert "agno==3.1.10" in agent_reqs
    assert "mcp==2.3.0" in agent_reqs
    platform_image = _text("deploy/Dockerfile.platform")
    agent_image = _text("deploy/Dockerfile.agent")
    assert "COPY cvplatform cvplatform" in platform_image
    assert "COPY --from=web /web/dist web/dist" in platform_image
    assert "requirements-platform.txt" in platform_image
    assert "COPY agent agent" in agent_image
    assert "cvplatform" not in agent_image
    assert "server.app" not in platform_image
    assert "server.app" not in agent_image
    compose = _text("deploy/docker-compose.yml")
    assert "platform-api" in compose
    assert "agent-worker" in compose
    assert "Dockerfile.platform" in compose
    assert "Dockerfile.agent" in compose
    assert "python\", \"-m\", \"cvplatform" in compose
    assert "python\", \"-m\", \"agent" in compose
    assert "rustfs" not in compose
    assert "comfyui" not in compose.lower().split("services:", 1)[-1]
    retired = _text("deploy/v2-compose.retired.yml")
    assert "已退役" in retired
    assert not (ROOT / "cli").exists()


def test_closed_loop_cli_web_and_catalog(monkeypatch, pg_database):
    monkeypatch.setenv("CVGEN_PLATFORM_DATABASE_URL", pg_database)
    monkeypatch.setenv("CVGEN_WEB_DIST", str(ROOT / "web" / "dist"))
    from cvplatform import db
    from cvplatform.app import app as platform_app

    db.reset_engine()
    with TestClient(platform_app) as platform:
        episode = platform.post("/api/episodes").json()["id"]
        health = platform.get("/api/health").json()
        assert health["process"] == "platform"
        assert health["service"] == "platform-api"

        from agent.app import app as agent_app

        with TestClient(agent_app) as agent:
            agent_health = agent.get("/api/health").json()
        assert agent_health["process"] == "agent"
        assert agent_health["service"] == "agent-worker"
        assert health["process"] != agent_health["process"]

        catalog = platform.get("/api/cli").json()
        names = [item["name"] for item in catalog["commands"]]
        assert "comic missing" in names
        assert "entity add" not in names
        assert "entity add Reference" not in names
        comic = next(item for item in catalog["commands"] if item["name"] == "comic missing")
        assert comic["method"] == "GET"
        assert comic["path"] == "/api/comic/missing"
        assert "--base" not in comic["usage"]

        cli = ROOT / "cvgen-cli" / "src"
        local_source = (cli / "local.rs").read_text()
        main_source = (cli / "main.rs").read_text()
        assert "/api/comic/missing" not in local_source
        assert "命令已移除" in main_source
        binary = _cvgen()
        home = ROOT / "tmp" / "cvgen-home"
        home.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config")}
        removed = subprocess.run(
            [str(binary), "entity", "add", "Reference", "{}"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert removed.returncode != 0
        assert "命令已移除" in removed.stderr

        config = Path(env["XDG_CONFIG_HOME"]) / "cvgen"
        config.mkdir(parents=True, exist_ok=True)
        (config / "auth.json").write_text(json.dumps({"base": "http://platform.test", "token": "device-token"}))
        missing = platform.get("/api/comic/missing", params={"episode_id": episode}).json()
        assert missing["stopped_at"]
        assert missing["local_h3"] is False

        output = _run_against_platform(binary, platform, episode, env)
        assert "停在：" in output
        assert missing["stopped_at"] in output
        assert "缺：" in output

        page = platform.get("/products")
        assert page.status_code == 200
        assert 'id="root"' in page.text
        products = platform.get("/api/products")
        assert products.status_code == 200
        assert "items" in products.json()
        script = (ROOT / "web" / "src" / "pages" / "products.jsx").read_text()
        assert "/api/products" in script
    db.reset_engine()


def _cvgen() -> Path:
    binary = ROOT / "cvgen-cli" / "target" / "debug" / "cvgen"
    subprocess.run(
        ["cargo", "build", "--bin", "cvgen"],
        cwd=ROOT / "cvgen-cli",
        check=True,
    )
    if not binary.is_file():
        pytest.fail("cvgen binary missing")
    return binary


def _run_against_platform(binary: Path, platform: TestClient, episode: str, env: dict) -> str:
    import threading
    import uvicorn

    config = uvicorn.Config(platform.app, host="127.0.0.1", port=8093, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            if platform.get("/api/health").status_code == 200 and _port_open():
                break
        except Exception:
            pass
        import time

        time.sleep(0.05)
    else:
        pytest.fail("platform did not listen on 8093")
    auth = Path(env["XDG_CONFIG_HOME"]) / "cvgen" / "auth.json"
    auth.write_text(json.dumps({"base": "http://127.0.0.1:8093", "token": "device-token"}))
    result = subprocess.run(
        [str(binary), "comic", "missing", "--episode", episode],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    server.should_exit = True
    thread.join(timeout=3)
    if result.returncode != 0:
        pytest.fail(result.stderr or result.stdout)
    return result.stdout


def _port_open() -> bool:
    import socket

    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", 8093)) == 0
