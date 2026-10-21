"""ffmpeg measurements and edits. The worker calls these; the agent does not."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class MediaError(RuntimeError):
    pass


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("ffmpeg 超时") from exc


def probe(path: Path) -> dict:
    result = _run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])
    data = json.loads(result.stdout.decode("utf-8") or "{}")
    video = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), {})
    return {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("avg_frame_rate"),
        "codec": video.get("codec_name"),
    }


def contact_sheet(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vf", "fps=1,scale=320:-1,tile=4x3", "-frames:v", "1", str(dest),
    ])
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])


def frame_at(src: Path, dest: Path, second: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = _run([
        "ffmpeg", "-y", "-v", "error", "-ss", str(second), "-i", str(src),
        "-frames:v", "1", str(dest),
    ])
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])


def loudness(path: Path) -> str:
    result = _run([
        "ffmpeg", "-v", "info", "-i", str(path), "-af", "volumedetect", "-f", "null", "-",
    ])
    text = result.stderr.decode("utf-8", "replace")
    lines = [line.strip() for line in text.splitlines() if "mean_volume" in line or "max_volume" in line]
    return "；".join(lines)


def join(sources: list[Path], dest: Path, fade: float = 2.0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    listing = dest.with_suffix(".txt")
    listing.write_text("".join(f"file '{path}'\n" for path in sources), encoding="utf-8")
    result = _run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c", "copy", str(dest),
    ])
    listing.unlink(missing_ok=True)
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])
    if fade:
        faded = dest.with_name(dest.stem + "-fade.mp4")
        info = probe(dest)
        start = max(0, info["duration"] - fade)
        fade_result = _run([
            "ffmpeg", "-y", "-v", "error", "-i", str(dest),
            "-vf", f"fade=t=out:st={start}:d={fade}",
            "-c:a", "copy", str(faded),
        ])
        if fade_result.returncode == 0:
            faded.replace(dest)


def passthrough(args: list[str], workdir: Path, timeout: int = 120) -> dict:
    from .rules import shell_forbidden

    if shell_forbidden(args):
        raise MediaError("参数不能带 shell 符号")
    result = _run(["ffmpeg", "-y", "-v", "error", *args], timeout=timeout)
    return {
        "code": result.returncode,
        "stderr": result.stderr.decode("utf-8", "replace")[-800:],
        "workdir": str(workdir),
    }
