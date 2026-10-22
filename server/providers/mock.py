"""Deterministic offline provider. Used by tests, demos, and dry runs; never bills.

Options (provider_instances.options):
- delay_seconds: how long an async video job "runs" (default 0)
- fail_times: fail the first N submissions (to exercise retries)
- replies: {schema_name: object} fixed LLM replies; otherwise a minimal object satisfying the schema
"""

from __future__ import annotations

import json
import subprocess
import time

from ..ontology import RESOLUTIONS
from .base import Adapter, Outcome, OutputFile, Progress, ProviderError, TaskContext, Usage

SIZES = {
    "480p横": (854, 480), "480p竖": (480, 854), "768p横": (1366, 768),
    "768p竖": (768, 1366), "480p(1:1)": (480, 480), "768p(1:1)": (768, 768),
}
_SUBMISSIONS: dict[str, int] = {}


def _ffmpeg(args: list[str]) -> None:
    result = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, timeout=120, check=False)
    if result.returncode != 0:
        raise ProviderError(result.stderr.decode("utf-8", "replace")[:300])


def example_for(schema: dict, root: dict | None = None) -> object:
    """Smallest value that satisfies common JSON Schema keywords. Enough for tests and dry runs."""
    root = root or schema
    if "$ref" in schema and schema["$ref"].startswith("#/"):
        node = root
        for part in schema["$ref"][2:].split("/"):
            node = node[part]
        return example_for(node, root)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return example_for(schema[key][0], root)
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), "null")
    if kind == "object" or "properties" in schema:
        return {name: example_for(sub, root) for name, sub in schema.get("properties", {}).items()}
    if kind == "array":
        count = max(1, int(schema.get("minItems", 1)))
        return [example_for(schema.get("items", {}), root) for _ in range(count)]
    if kind == "integer":
        low = schema.get("minimum", 1)
        high = schema.get("maximum", low)
        return int(max(low, min(5, high)))
    if kind == "number":
        return float(schema.get("minimum", 1))
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    text = schema.get("description") or schema.get("title") or "示例"
    return str(text)[: int(schema.get("maxLength", 40))] or "示例"


class MockAdapter(Adapter):
    protocol = "mock"
    poll_interval = 0.2

    def __init__(self, instance):
        super().__init__(instance)
        self.kind = instance.kind
        self.sync = instance.kind != "video"

    def _maybe_fail(self, ctx: TaskContext) -> None:
        limit = int(self.instance.options.get("fail_times", 0))
        key = f"{self.instance.name}:{ctx.task_id}"
        _SUBMISSIONS[key] = _SUBMISSIONS.get(key, 0) + 1
        if _SUBMISSIONS[key] <= limit:
            raise ProviderError(f"模拟失败（第 {_SUBMISSIONS[key]} 次）")

    def run(self, request: dict, ctx: TaskContext) -> Outcome:
        self._maybe_fail(ctx)
        if self.kind == "llm":
            replies = self.instance.options.get("replies") or {}
            reply = replies.get(request.get("schema_name") or "") or example_for(request.get("schema") or {"type": "object"})
            text = json.dumps(reply, ensure_ascii=False)
            tokens_in = sum(len(item.get("content", "")) for item in request.get("messages", [])) + len(request.get("system") or "")
            return Outcome(data={"json": reply, "raw": text, "model": self.instance.model or "mock"},
                           usage=[Usage("token_in", tokens_in), Usage("token_out", len(text))])
        if self.kind == "image":
            files = []
            for index in range(max(1, int(request.get("n") or 1))):
                dest = ctx.workdir / f"mock-image-{index}.png"
                _ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size=768x432:rate=1:duration=1", "-frames:v", "1", str(dest)])
                files.append(OutputFile(dest, "image/png", f"候选 {index + 1}"))
            return Outcome(files=files, usage=[Usage("image", len(files))])
        if self.kind in {"tts", "music"}:
            seconds = int(request.get("duration") or 3)
            dest = ctx.workdir / f"mock-{self.kind}.wav"
            _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}:sample_rate=44100", str(dest)])
            return Outcome(files=[OutputFile(dest, "audio/wav")], usage=[Usage("audio_second", seconds)])
        raise ProviderError(f"模拟供应商不支持 {self.kind}")

    def submit(self, request: dict, ctx: TaskContext) -> dict:
        self._maybe_fail(ctx)
        resolution = request.get("resolution") or "768p横"
        if resolution not in RESOLUTIONS:
            raise ProviderError("分辨率不在档位里")
        return {
            "mock_id": ctx.task_id,
            "started": time.time(),
            "duration": int(request.get("duration") or 5),
            "resolution": resolution,
        }

    def poll(self, ref: dict, ctx: TaskContext) -> Progress | Outcome:
        delay = float(self.instance.options.get("delay_seconds", 0))
        elapsed = time.time() - float(ref.get("started", 0))
        if elapsed < delay:
            return Progress(fraction=min(0.99, elapsed / delay) if delay else None, message="模拟渲染中")
        width, height = SIZES[ref.get("resolution") or "768p横"]
        seconds = int(ref.get("duration") or 5)
        dest = ctx.workdir / "mock-video.mp4"
        _ffmpeg([
            "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate=12:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
        ])
        return Outcome(files=[OutputFile(dest, "video/mp4")],
                       usage=[Usage("video_second", seconds), Usage("gpu_second", max(elapsed, 0.01))])

    def cancel(self, ref: dict, ctx: TaskContext) -> bool:
        return True

    def estimate(self, request: dict) -> list[Usage]:
        if self.kind == "video":
            return [Usage("video_second", int(request.get("duration") or 5))]
        if self.kind == "image":
            return [Usage("image", int(request.get("n") or 1))]
        if self.kind == "llm":
            return [Usage("token_in", 2000), Usage("token_out", 1000)]
        return [Usage("call", 1)]

    def probe(self) -> dict:
        return {"reachable": True, "message": "模拟供应商，总是可用", "latency_ms": 0}

    def list_models(self) -> list[str]:
        return ["mock"]


def reset() -> None:
    _SUBMISSIONS.clear()

