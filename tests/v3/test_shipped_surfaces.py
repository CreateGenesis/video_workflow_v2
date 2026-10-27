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
    settings = read("web/src/pages/settings.jsx")
    assert 'data-testid="verify-button"' in settings
    assert "示例" in settings
    run_new = read("web/src/pages/run-new.jsx")
    assert "不能新开一条灵感出片运行" in run_new


def test_cvgen_missing_command_does_not_build_an_h3_body():
    source = read("cvgen-cli/src/local.rs")
    start = source.index("fn comic_missing")
    body = source[start:start + 700]
    assert "comic_missing" in body
    assert "ref_image_0" not in body
    assert "Authorization" not in body
    assert "本地拼 H3" in source


def test_new_process_does_not_register_comfy_gpu():
    app = read("cvplatform/app.py")
    assert "video.comfy-gpu1" not in app
    assert "comfyui.py" not in app
    compose = read("deploy/v3-compose.yml")
    assert "platform-api" in compose
    assert "agent-worker" in compose
    assert "comfy" not in compose.lower()
