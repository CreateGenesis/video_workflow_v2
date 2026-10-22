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
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    return {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("avg_frame_rate"),
        "codec": video.get("codec_name"),
        "has_audio": bool(audio),
        "audio_codec": audio.get("codec_name"),
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
    """Hard-cut the pictures, then fade the ending. Video-only inputs stay video-only."""
    if len(sources) < 2:
        raise MediaError("拼接至少要两条成片")
    dest.parent.mkdir(parents=True, exist_ok=True)
    probed = [probe(path) for path in sources]
    duration = sum(item["duration"] for item in probed)
    if duration <= 0:
        raise MediaError("成片没有可测量的时长")
    fade = min(max(fade, 0), 3, duration)
    start = max(0, duration - fade)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for path in sources:
        cmd.extend(["-i", str(path)])
    parts = []
    offset = 0.0
    for index, info in enumerate(probed):
        parts.append(f"[{index}:v]scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=12,setpts=PTS-STARTPTS+{offset}/TB[v{index}]")
        offset += info["duration"]
    joined = "".join(f"[v{index}]" for index in range(len(sources)))
    video = f"{joined}concat=n={len(sources)}:v=1:a=0,format=yuv420p"
    if fade:
        video += f",fade=t=out:st={start}:d={fade}"
    parts.append(video + "[outv]")
    cmd.extend([
        "-filter_complex", ";".join(parts),
        "-map", "[outv]", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
    ])
    result = _run(cmd)
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])


def mix_narration(picture: Path, narration: Path, dest: Path, sfx: Path | None = None) -> str:
    """Put IndexTTS2 under the picture. SFX +8 dB, limit about -1 dB, duck under the voice."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = probe(picture)["duration"]
    if duration <= 0:
        raise MediaError("画面没有可测量的时长")
    bed = sfx or _action_bed(dest.with_name(dest.stem + "-sfx.wav"), duration)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(picture), "-i", str(narration), "-i", str(bed)]
    graph = (
        "[2:a]volume=8dB[sfx];"
        "[1:a]asplit=2[voice][key];"
        "[sfx][key]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=250[ducked];"
        "[ducked][voice]amix=inputs=2:duration=longest:dropout_transition=0,alimiter=limit=0.891[outa]"
    )
    cmd.extend([
        "-filter_complex", graph,
        "-map", "0:v:0", "-map", "[outa]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-t", f"{duration:.3f}", str(dest),
    ])
    result = _run(cmd)
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])
    return graph


def _action_bed(dest: Path, duration: float) -> Path:
    """Action-sound bed used when the edit has no separate SFX clip."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = _run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"anoisesrc=color=pink:duration={max(duration, 0.2):.3f}:sample_rate=44100",
        "-c:a", "pcm_s16le", str(dest),
    ])
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])
    return dest


def mix_score(picture: Path, music: Path, dest: Path, narration: Path | None = None) -> str:
    """Music +8 dB, limit about -1 dB, duck under narration when a voice exists."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = probe(picture)["duration"]
    if duration <= 0:
        raise MediaError("画面没有可测量的时长")
    if narration:
        graph = (
            "[1:a]volume=8dB[score];"
            "[2:a]asplit=2[voice][key];"
            "[score][key]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=250[ducked];"
            "[ducked][voice]amix=inputs=2:duration=longest:dropout_transition=0,alimiter=limit=0.891[outa]"
        )
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(picture), "-i", str(music), "-i", str(narration)]
    else:
        graph = "[1:a]volume=8dB,alimiter=limit=0.891[outa]"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(picture), "-i", str(music)]
    cmd.extend([
        "-filter_complex", graph,
        "-map", "0:v:0", "-map", "[outa]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-t", f"{duration:.3f}", str(dest),
    ])
    result = _run(cmd)
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])
    return graph


def burn_lines(picture: Path, lines: list[str], dest: Path) -> None:
    """Burn dialogue or lyrics only when they must stay on screen."""
    text = "\n".join(line.strip() for line in lines if line.strip())
    if not text:
        raise MediaError("没有台词，不能烧录字幕")
    dest.parent.mkdir(parents=True, exist_ok=True)
    caption = dest.with_suffix(".srt")
    caption.write_text(_srt(text, probe(picture)["duration"]), encoding="utf-8")
    result = _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(picture),
        "-vf", f"subtitles={caption}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", str(dest),
    ])
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:400])


def _srt(text: str, duration: float) -> str:
    end = max(duration, 0.5)
    return f"1\n00:00:00,000 --> {_stamp(end)}\n{text}\n"


def _stamp(second: float) -> str:
    whole = int(second)
    millis = int(round((second - whole) * 1000))
    hours, remain = divmod(whole, 3600)
    minutes, secs = divmod(remain, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


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
