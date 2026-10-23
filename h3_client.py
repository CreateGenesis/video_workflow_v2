"""Standalone MiniMax H3 client for the AutoDL ComfyUI workflow minimax_h3_zm_u24 (manual testing).

Reads AUTODL_API_TOKEN from .env. The token is never printed or written to disk.
This file only submits, queries, and downloads. It does not build prompts.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGE_SLOTS = 9
AUDIO_SLOTS = 3
RESOLUTIONS = (
    "480p横",
    "480p竖",
    "768p横",
    "768p竖",
    "480p(1:1)",
    "768p(1:1)",
)
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/flac", "audio/x-wav", "audio/mp4"}


class H3Error(RuntimeError):
    pass


def load_env(path: Path | None = None) -> dict[str, str]:
    env_path = path or ROOT / ".env"
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def config() -> dict[str, str]:
    """Standalone tool: credentials come from the environment or .env. The service uses
    server/providers/autodl.py with the provider instance stored in the database instead."""
    file_env = load_env()
    token = os.environ.get("AUTODL_API_TOKEN") or file_env.get("AUTODL_API_TOKEN")
    if not token:
        raise H3Error("AUTODL_API_TOKEN is missing")
    base = (os.environ.get("AUTODL_API_BASE") or file_env.get("AUTODL_API_BASE") or "https://www.autodl.art").rstrip("/")
    workflow = os.environ.get("H3_WORKFLOW_ID") or file_env.get("H3_WORKFLOW_ID") or "minimax_h3_zm_u24"
    return {"token": token, "base": base, "workflow": workflow}


def _request(url: str, token: str, body: dict | None = None, timeout: int = 120) -> tuple[int, dict]:
    data = None
    headers = {
        "Authorization": token,
        "Accept": "application/json",
        "User-Agent": "video-gen-h3",
    }
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise H3Error(f"non-json response HTTP {status}: {raw[:300]!r}") from exc
    if not isinstance(payload, dict):
        raise H3Error(f"unexpected response HTTP {status}")
    return status, payload


def _media_value(source: str, kind: str) -> str:
    if source.startswith(("http://", "https://", "data:")):
        return source
    path = Path(source)
    if not path.is_file():
        raise H3Error(f"{kind} not found: {source}")
    mime = mimetypes.guess_type(path.name)[0] or ""
    allowed = IMAGE_TYPES if kind == "image" else AUDIO_TYPES
    if mime not in allowed:
        raise H3Error(f"{kind} type {mime or 'unknown'} is not accepted for {path.name}")
    import base64

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_body(
    prompt: str,
    images: list[str] | None = None,
    audios: list[str] | None = None,
    duration: int = 5,
    resolution: str = "768p横",
    seed: int | None = None,
) -> dict:
    text = prompt.strip()
    if not text:
        raise H3Error("prompt is empty")
    if len(text) > 20000:
        raise H3Error("prompt is longer than 20000 characters")
    if not isinstance(duration, int) or not 1 <= duration <= 15:
        raise H3Error("duration must be an integer from 1 to 15")
    if resolution not in RESOLUTIONS:
        raise H3Error("resolution must be one of: " + ", ".join(RESOLUTIONS))
    images = images or []
    audios = audios or []
    if not images:
        raise H3Error("this workflow requires ref_image_0")
    if len(images) > IMAGE_SLOTS:
        raise H3Error(f"at most {IMAGE_SLOTS} reference images")
    if len(audios) > AUDIO_SLOTS:
        raise H3Error(f"at most {AUDIO_SLOTS} reference audios")

    body: dict = {
        "prompt": text,
        "duration": duration,
        "resolution": resolution,
    }
    for index, source in enumerate(images):
        body[f"ref_image_{index}"] = _media_value(source, "image")
    for index, source in enumerate(audios):
        body[f"ref_audio_{index}"] = _media_value(source, "audio")
    if seed is not None:
        if not isinstance(seed, int) or seed < 0:
            raise H3Error("seed must be an integer >= 0")
        body["seed"] = seed
    return body


def submit(body: dict) -> dict:
    cfg = config()
    url = f"{cfg['base']}/api/v1/comfyui/comfyui_workflow/{cfg['workflow']}"
    status, payload = _request(url, cfg["token"], body)
    if status == 401:
        raise H3Error("token rejected")
    if status == 403:
        raise H3Error("forbidden or insufficient balance")
    if status != 200 or payload.get("code") not in (None, "Success"):
        raise H3Error(f"submit failed HTTP {status}: {payload.get('msg') or payload.get('code')}")
    data = payload.get("data") or {}
    task_id = data.get("task_id")
    if not task_id:
        raise H3Error("submit response has no task_id; do not resubmit blindly")
    return {
        "task_id": task_id,
        "status": data.get("status"),
        "workflow": data.get("workflow") or cfg["workflow"],
        "request_id": payload.get("request_id"),
    }


def query(task_id: str) -> dict:
    cfg = config()
    url = f"{cfg['base']}/api/v1/comfyui/comfyui_workflow/result/{task_id}"
    status, payload = _request(url, cfg["token"])
    if status == 401:
        raise H3Error("token rejected")
    data = payload.get("data") or {}
    results = data.get("results") or []
    video_url = ""
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict) and item.get("url"):
                video_url = item["url"]
                break
    return {
        "http_status": status,
        "code": payload.get("code"),
        "msg": payload.get("msg") or "",
        "task_id": data.get("task_id") or task_id,
        "status": data.get("status"),
        "video_url": video_url,
        "results": results,
        "request_id": payload.get("request_id"),
    }


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")
    req = urllib.request.Request(url, headers={"User-Agent": "video-gen-h3"})
    with urllib.request.urlopen(req, timeout=180) as response, partial.open("wb") as handle:
        while chunk := response.read(1 << 20):
            handle.write(chunk)
    partial.replace(dest)
    return dest


def wait(task_id: str, limit: int = 1500, interval: int = 15) -> dict:
    started = time.time()
    while time.time() - started < limit:
        state = query(task_id)
        print(f"[{int(time.time() - started)}s] {state.get('status') or state.get('code')}", flush=True)
        status = str(state.get("status") or "").lower()
        if state.get("video_url") or status in {"completed", "success", "succeeded"}:
            return state
        if status in {"failed", "error", "canceled", "cancelled"}:
            return state
        if state.get("code") not in (None, "Success") and status in {"", "none"}:
            return state
        time.sleep(interval)
    raise H3Error("still running; query again later")


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8-sig")
    if args.prompt:
        return args.prompt
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise H3Error("pass --prompt, --prompt-file, or a prompt on stdin")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Call the AutoDL MiniMax H3 workflow.")
    sub = parser.add_subparsers(dest="action", required=True)

    submit_parser = sub.add_parser("submit", help="submit one generation")
    submit_parser.add_argument("--prompt")
    submit_parser.add_argument("--prompt-file")
    submit_parser.add_argument("--image", action="append", default=[], help="image URL or local file; repeat up to 9")
    submit_parser.add_argument("--audio", action="append", default=[], help="audio URL or local file; repeat up to 3")
    submit_parser.add_argument("--duration", type=int)
    submit_parser.add_argument("--resolution")
    submit_parser.add_argument("--seed", type=int)
    submit_parser.add_argument("--dry-run", action="store_true", help="print the body shape without calling the API")

    query_parser = sub.add_parser("query", help="query one task")
    query_parser.add_argument("task_id")

    wait_parser = sub.add_parser("wait", help="poll until the task finishes")
    wait_parser.add_argument("task_id")
    wait_parser.add_argument("--download")
    wait_parser.add_argument("--limit", type=int, default=1500)

    download_parser = sub.add_parser("download", help="download a result URL")
    download_parser.add_argument("url")
    download_parser.add_argument("dest")

    args = parser.parse_args(argv)
    if args.action == "submit":
        file_env = load_env()
        duration = args.duration if args.duration is not None else int(os.environ.get("H3_DURATION") or file_env.get("H3_DURATION") or 5)
        resolution = args.resolution or os.environ.get("H3_RESOLUTION") or file_env.get("H3_RESOLUTION") or "768p横"
        body = build_body(_read_prompt(args), args.image, args.audio, duration, resolution, args.seed)
        if args.dry_run:
            safe = {key: ("<media>" if key.startswith("ref_") else value) for key, value in body.items()}
            print(json.dumps({"workflow": config()["workflow"], "body": safe}, ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(submit(body), ensure_ascii=False))
        return 0
    if args.action == "query":
        print(json.dumps(query(args.task_id), ensure_ascii=False, indent=2))
        return 0
    if args.action == "wait":
        state = wait(args.task_id, args.limit)
        if args.download and state.get("video_url"):
            path = download(state["video_url"], Path(args.download))
            state = {**state, "file": str(path), "bytes": path.stat().st_size}
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    path = download(args.url, Path(args.dest))
    print(json.dumps({"file": str(path), "bytes": path.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except H3Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
