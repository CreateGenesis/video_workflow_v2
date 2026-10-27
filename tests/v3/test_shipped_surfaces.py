"""Shipped surfaces: product page, verify button, no inspiration-to-video, no Comfy registration."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_product_page_and_verify_button_exist():
    routes = read("web/src/lib/routes.js")
    assert "/products" in routes
    page = read("web/src/pages/products.jsx")
    assert "搜索提示词" in page
    assert "/api/products" in page
    settings = read("web/src/pages/settings.jsx")
    assert 'data-testid="verify-button"' in settings
    assert "示例" in settings
    actions = read("web/src/lib/v3-actions.js")
    assert "不能新开一条灵感出片运行" in actions


def test_cvgen_missing_command_does_not_build_an_h3_body():
    local = read("cvgen-cli/src/local.rs")
    main = read("cvgen-cli/src/main.rs")
    catalog = read("cvplatform/catalog.py")
    assert 'name: "comic missing"' not in local
    assert "/api/comic/missing" not in local
    assert "ref_image_0" not in main
    assert "客户端不能在本地拼 H3" in main
    assert '"/api/comic/missing"' in catalog
    assert "entity add" not in catalog.split("REMOVED", 1)[0]


def test_new_process_does_not_register_comfy_gpu():
    app = read("cvplatform/app.py")
    assert "video.comfy-gpu1" not in app
    assert "comfyui.py" not in app
    compose = read("deploy/docker-compose.yml")
    assert "platform-api" in compose
    assert "agent-worker" in compose
    assert "comfy" not in compose.lower().split("services:", 1)[-1]
