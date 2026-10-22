"""Saved provider settings override env. Keys stay on the server."""

from __future__ import annotations

import os
from pathlib import Path

CAPABILITIES = ("video", "image", "music")
FIELDS = ("base", "key", "workflow")
ENV = {
    "video": ("AUTODL_API_BASE", "AUTODL_API_TOKEN", "H3_WORKFLOW_ID"),
    "image": ("CVGEN_IMAGE_BASE", "CVGEN_IMAGE_KEY", "CVGEN_IMAGE_WORKFLOW"),
    "music": ("CVGEN_MUSIC_BASE", "CVGEN_MUSIC_KEY", "CVGEN_MUSIC_WORKFLOW"),
}
VIDEO_DEFAULTS = ("https://www.autodl.art", "", "minimax_h3_zm_u24")


def mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return "••••"
    return "••••" + secret[-4:]


def _file_env() -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_value(name: str, file_env: dict[str, str]) -> str:
    return os.environ.get(name) or file_env.get(name) or ""


def resolve(store, capability: str) -> dict[str, str]:
    """Return base, key, and workflow. A saved value wins over the same env name."""
    if capability not in CAPABILITIES:
        raise ValueError("没有这个能力")
    file_env = _file_env()
    names = ENV[capability]
    defaults = VIDEO_DEFAULTS if capability == "video" else ("", "", "")
    resolved = {}
    for field, env_name, default in zip(FIELDS, names, defaults):
        saved = store.setting(f"provider:{capability}:{field}", "")
        resolved[field] = saved or _env_value(env_name, file_env) or default
    resolved["source"] = "saved" if any(store.setting(f"provider:{capability}:{field}", "") for field in FIELDS) else "env"
    return resolved


def configured(store, capability: str) -> bool:
    item = resolve(store, capability)
    return bool(item["base"] and item["key"] and item["workflow"])


def public_view(store) -> list[dict]:
    rows = []
    for capability in CAPABILITIES:
        item = resolve(store, capability)
        rows.append({
            "capability": capability,
            "configured": bool(item["base"] and item["key"] and item["workflow"]),
            "base": item["base"],
            "workflow": item["workflow"],
            "key": mask(item["key"]),
        })
    return rows


def save(store, capability: str, base: str, key: str, workflow: str) -> None:
    if capability not in CAPABILITIES:
        raise ValueError("没有这个能力")
    if not base.strip() or not workflow.strip():
        raise ValueError("地址和工作流编号不能为空")
    current = store.setting(f"provider:{capability}:key", "")
    secret = key.strip() or current
    if not secret and not _env_value(ENV[capability][1], _file_env()):
        raise ValueError("访问密钥不能为空")
    store.set_setting(f"provider:{capability}:base", base.strip().rstrip("/"))
    store.set_setting(f"provider:{capability}:workflow", workflow.strip())
    if secret:
        store.set_setting(f"provider:{capability}:key", secret)
