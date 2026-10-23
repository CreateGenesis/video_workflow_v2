"""Tasks that run on the application host with ffmpeg: check, edit, pull, inspect, frame, ffmpeg."""

from __future__ import annotations

import re
import shutil
import subprocess

import httpx

from .. import db, graph
from ..db import get_setting
from ..media import (
    MediaError, burn_lines, contact_sheet, frame_at, join, loudness, mix_score, passthrough, probe,
)
from ..providers.base import InputError
from ..rules import RESOLUTION_SIZE, check_spec
from ..workflows.template import ENTITY_ID
from . import tasks as task_q
from .job import Job

MAX_PULL_BYTES = 2 * 1024 ** 3
QUOTED = re.compile(r"[“\"「](.+?)[”\"」]")


def _finish(conn, job: Job, output: dict) -> None:
    from ..workflows.runner import task_finished

    task_q.complete(conn, job.id, output)
    task_finished(conn, job.task, job.principal)


def _entity(conn, entity_id: str) -> dict:
    entity = graph.require_entity(conn, entity_id)
    if not entity.get("artifact_id"):
        raise InputError(f"{entity['data'].get('title') or entity_id} 没有文件")
    return entity


def run_check(job: Job) -> None:
    from ..workflows.runner import handle_check

    with db.tx(lock_run=job.task.get("run_id")) as conn:
        if job.is_workflow:
            upstream_node = job.node["for_each"].split(".", 1)[0]
            upstream = job.upstream_output(conn, upstream_node)
            clip_id = upstream.get("clip_id")
            rules = job.node.get("rules") or ["duration", "resolution"]
            resolution = upstream.get("resolution") or ""
            shot_id = upstream.get("shot_id")
        else:
            clip_id = job.input["clip_id"]
            rules = job.input.get("rules") or ["duration", "resolution", "contact_sheet"]
            clip = graph.require_entity(conn, clip_id)
            resolution = job.input.get("resolution") or clip["data"].get("resolution") or ""
            shot_id = None
        if not clip_id:
            raise InputError("上游没有成片可检查")
        clip = _entity(conn, clip_id)
        local = job.local(conn, clip["artifact_id"])
        shot = graph.get_entity(conn, shot_id) if shot_id else None
    info = probe(local)
    problems: list[str] = []
    output: dict = {"clip_id": clip_id, "probe": info, "rules": rules}
    if "duration" in rules or "resolution" in rules:
        found = check_spec(float(info.get("duration") or 0), info.get("width"), info.get("height"), resolution)
        problems += [item for item in found if ("时长" in item and "duration" in rules) or ("分辨率" in item and "resolution" in rules)]
        if "duration" in rules and shot and shot["data"].get("duration"):
            expected = float(shot["data"]["duration"])
            if abs(float(info.get("duration") or 0) - expected) > 1.0:
                problems.append(f"时长 {info.get('duration'):.1f} 秒和镜头要求的 {expected:.0f} 秒差超过 1 秒")
    if "loudness" in rules:
        output["loudness"] = loudness(local)
    if "dialogue" in rules and shot:
        spoken = QUOTED.findall(" ".join(str(item.get("action", "")) for item in shot["data"].get("paragraphs") or [])
                                + str(shot["data"].get("action", "")))
        if spoken and not info.get("has_audio"):
            problems.append("镜头里有台词，但成片没有声音")
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        if "contact_sheet" in rules:
            sheet = job.workdir / "sheet.jpg"
            contact_sheet(local, sheet)
            output["sheet_artifact_id"] = job.store(conn, sheet, kind="sheet", label="接触表")["id"]
        if "last_frame" in rules:
            last = job.workdir / "last.jpg"
            frame_at(local, last, max(0.0, float(info.get("duration") or 0) - 0.1))
            output["last_frame_artifact_id"] = job.store(conn, last, kind="frame", label="尾帧")["id"]
        output["problems"] = problems
        output["passed"] = not problems
        if job.is_workflow:
            output.update(handle_check(conn, job.principal, {**job.task, "problems": problems}, not problems))
        _finish(conn, job, output)


def _path_values(conn, job: Job, path: str) -> list:
    """Resolve an edit path to clip entity ids (node outputs) or an asset's artifact."""
    head, _, rest = path.partition(".")
    if head == "assets":
        scope = job.scope(conn)
        return [scope.lookup(path)]
    rows = conn.execute(db.tasks.select().where(
        db.tasks.c.run_id == job.task["run_id"], db.tasks.c.node_id == head, db.tasks.c.superseded_by.is_(None),
    ).order_by(db.tasks.c.item_index)).mappings().all()
    values = []
    for row in rows:
        output = row["output"] or {}
        values.append(output.get(rest) if rest else output.get("clip_id"))
    return [value for value in values if value]


def _audio_file(conn, job: Job, values: list):
    from ..workflows.template import AssetRef

    paths = []
    for value in values:
        if isinstance(value, str) and value.startswith("asset:"):
            from .. import assets

            version = assets.resolve(conn, job.task["workspace_id"], value)
            value = AssetRef(ref=value, kind=version["kind"], data=version["data"], title=version["title"],
                             artifact_id=version.get("artifact_id"))
        if isinstance(value, AssetRef):
            if not value.artifact_id:
                raise InputError(f"素材 {value.ref} 没有文件")
            paths.append(job.local(conn, value.artifact_id))
        else:
            paths.append(job.local(conn, _entity(conn, value)["artifact_id"]))
    if not paths:
        return None
    if len(paths) == 1:
        return paths[0]
    listing = job.workdir / "narration.txt"
    listing.write_text("".join(f"file '{path.name}'\n" for path in paths), encoding="utf-8")
    merged = job.workdir / "narration.wav"
    result = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", listing.name,
                             "-c:a", "pcm_s16le", merged.name], cwd=job.workdir, capture_output=True, check=False)
    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf-8", "replace")[:300])
    return merged


def run_edit(job: Job) -> None:
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        if job.is_workflow:
            ops = job.node["ops"]
            clip_ids = _path_values(conn, job, job.node["clips"]) if job.node.get("clips") else []
            name = "成片"
            scope = job.scope(conn)
        else:
            ops = job.input.get("ops") or [{"op": "join"}]
            clip_ids = list(job.input.get("clips") or [])
            name = job.input.get("title") or "剪辑成片"
            scope = None
        if not clip_ids:
            raise InputError("剪辑没有成片")
        sources = [job.local(conn, _entity(conn, clip_id)["artifact_id"]) for clip_id in clip_ids]
        extras = {}
        for index, op in enumerate(ops):
            if op["op"] == "mix":
                music = op.get("music")
                narration = op.get("narration")
                if job.is_workflow:
                    extras[index] = {
                        "music": _audio_file(conn, job, _path_values(conn, job, music)) if music else None,
                        "narration": _audio_file(conn, job, _path_values(conn, job, narration)) if narration else None,
                    }
                else:
                    extras[index] = {
                        "music": _audio_file(conn, job, [music]) if music else None,
                        "narration": _audio_file(conn, job, [narration]) if narration else None,
                    }
            if op["op"] == "subtitle":
                if job.is_workflow:
                    lines = [graph.require_entity(conn, value)["data"].get("text", "") if isinstance(value, str) and ENTITY_ID.match(value)
                             else str(value) for value in _path_values(conn, job, op["lines"])]
                else:
                    lines = list(op.get("lines") or [])
                extras[index] = {"lines": lines}
            if op["op"] == "export" and op.get("name"):
                name = scope.render(op["name"]) if scope else op["name"]
    current = job.workdir / "cut-0.mp4"
    join_op = next((op for op in ops if op["op"] == "join"), None)
    if len(sources) > 1:
        join(sources, current, fade=float((join_op or {}).get("fade_seconds", 0.0)))
    else:
        shutil.copyfile(sources[0], current)
    report = []
    for index, op in enumerate(ops):
        step = job.workdir / f"cut-{index + 1}.mp4"
        if op["op"] == "mix":
            music = extras[index]["music"]
            if not music:
                raise InputError("混音需要配乐")
            report.append({"mix": mix_score(current, music, step, extras[index]["narration"])})
            current = step
        elif op["op"] == "subtitle":
            burn_lines(current, extras[index]["lines"], step)
            current = step
        elif op["op"] == "export" and op.get("resolution"):
            width, height = RESOLUTION_SIZE[op["resolution"]]
            result = subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-i", current.name,
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", step.name,
            ], cwd=job.workdir, capture_output=True, check=False)
            if result.returncode != 0:
                raise MediaError(result.stderr.decode("utf-8", "replace")[:300])
            current = step
    final = job.workdir / f"{re.sub(r'[^0-9A-Za-z_-]+', '-', name).strip('-') or 'final'}.mp4"
    shutil.copyfile(current, final)
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        artifact = job.store(conn, final, kind="video", label=name)
        clip = graph.add_entity(conn, job.principal, job.task["work_id"], "Clip", {
            "title": name, "duration": artifact["duration"],
        }, artifact_id=artifact["id"], run_id=job.task.get("run_id"))
        graph.add_link(conn, job.principal, job.task["work_id"], "derived_from", clip["id"], clip_ids[0], "剪辑导出")
        export = {"artifact_id": artifact["id"], "clip_id": clip["id"], "name": name}
        _finish(conn, job, {**export, "export": export, "duration": artifact["duration"], "clips": clip_ids,
                            "steps": report})


def run_pull(job: Job) -> None:
    url = job.input["url"]
    if not re.match(r"^https?://", url):
        raise InputError("只能拉取 http(s) 地址")
    dest = job.workdir / "pulled"
    size = 0
    try:
        with httpx.stream("GET", url, timeout=httpx.Timeout(300.0, connect=15.0), follow_redirects=True,
                          headers={"User-Agent": "cvgen"}) as response:
            response.raise_for_status()
            mime = response.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(1 << 20):
                    size += len(chunk)
                    if size > MAX_PULL_BYTES:
                        raise InputError("文件超过 2 GB，不拉取")
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        raise InputError(f"拉取失败：{exc}") from exc
    suffix = {"video/mp4": ".mp4", "video/webm": ".webm", "image/png": ".png", "image/jpeg": ".jpg",
              "image/webp": ".webp", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav"}.get(mime, "")
    named = dest.with_suffix(suffix) if suffix else dest
    dest.rename(named)
    title = job.input.get("title") or url.rsplit("/", 1)[-1][:60] or url[:60]
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        artifact = job.store(conn, named, mime=mime, label=title, source_url=url)
        entity = None
        if artifact["kind"] in {"image", "video", "audio"}:
            entity = graph.add_entity(conn, job.principal, job.task["work_id"], "Reference", {
                "title": title, "role": job.input.get("role") or "风格", "source_url": url,
                "take": job.input.get("take") or "", "ignore": job.input.get("ignore") or "",
            }, artifact_id=artifact["id"])
        output = {"artifact_id": artifact["id"], "entity_id": entity["id"] if entity else None, "mime": mime}
        if job.input.get("learn"):
            observation = graph.add_entity(conn, job.principal, job.task["work_id"], "Observation", {
                "title": f"学习：{title}", "summary": "服务已下载并入库。接着用 cvgen inspect 量时长、声音和接触表。",
            })
            output["observation_id"] = observation["id"]
        _finish(conn, job, output)


def run_inspect(job: Job) -> None:
    mode = job.input.get("mode") or "inspect"
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        entity = _entity(conn, job.input["entity_id"])
        local = job.local(conn, entity["artifact_id"])
    info = probe(local)
    output: dict = {"probe": info, "entity_id": entity["id"], "mode": mode}
    is_video = bool(info.get("width")) and float(info.get("duration") or 0) > 0.5
    if info.get("has_audio"):
        output["loudness"] = loudness(local)
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        if is_video:
            sheet = job.workdir / "sheet.jpg"
            contact_sheet(local, sheet)
            output["sheet_artifact_id"] = job.store(conn, sheet, kind="sheet", label="接触表")["id"]
        summary = (f"{info.get('duration', 0):.1f} 秒，{info.get('width')}x{info.get('height')}，"
                   f"{'有' if info.get('has_audio') else '没有'}声音。{output.get('loudness', '')}")
        observation = graph.add_entity(conn, job.principal, job.task["work_id"], "Observation", {
            "title": f"检视：{entity['data'].get('title') or entity['id']}", "summary": summary,
        })
        output["observation_id"] = observation["id"]
        if mode == "reverse":
            output["draft"] = ("先按接触表复述镜头、动作和声音，确认后再写提示词。声音没测到的不要编。"
                               f"测量：{summary}")
        if mode == "style":
            style = graph.add_entity(conn, job.principal, job.task["work_id"], "Style", {
                "title": f"提取自 {entity['data'].get('title') or entity['id']}",
                "medium": f"{info.get('width')}x{info.get('height')} {info.get('codec') or ''}".strip(),
                "grade": "从接触表观察后补写", "ban": "禁止定格。",
            })
            output["style_id"] = style["id"]
        _finish(conn, job, output)


def run_frame(job: Job) -> None:
    role = job.input.get("role") or "空间"
    if role not in {"首帧", "尾帧", "空间"}:
        raise InputError("抽帧用途只能是首帧、尾帧或空间")
    at = job.input.get("at") or "last"
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        clip = _entity(conn, job.input["clip_id"])
        local = job.local(conn, clip["artifact_id"])
    info = probe(local)
    second = 0.0 if at == "first" else (max(0.0, float(info.get("duration") or 0) - 0.1) if at == "last" else float(at))
    dest = job.workdir / "frame.jpg"
    frame_at(local, dest, second)
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        artifact = job.store(conn, dest, kind="frame", label=f"{clip['data'].get('title')} {at}")
        reference = graph.add_entity(conn, job.principal, job.task["work_id"], "Reference", {
            "title": "上一镜尾帧" if at == "last" else f"成片 {at} 帧", "role": role,
            "take": "只采用画面里的空间和人物位置", "ignore": "不采用这一帧里已经结束的动作",
        }, artifact_id=artifact["id"])
        graph.add_link(conn, job.principal, job.task["work_id"], "derived_from", reference["id"], clip["id"], f"抽自 {at}")
        _finish(conn, job, {"artifact_id": artifact["id"], "entity_id": reference["id"], "at": at, "role": role})


def run_ffmpeg(job: Job) -> None:
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        if not get_setting(conn, "ffmpeg_passthrough", False):
            raise InputError("ffmpeg 透传没有打开（管理员在设置里打开）")
        for name, artifact_id in (job.input.get("inputs") or {}).items():
            if not re.match(r"^[A-Za-z0-9_.-]+$", name):
                raise InputError(f"输入文件名不合法：{name}")
            shutil.copyfile(job.local(conn, artifact_id), job.workdir / name)
    result = passthrough(list(job.input.get("args") or []), job.workdir)
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        stored = {}
        for name in job.input.get("outputs") or []:
            path = (job.workdir / name).resolve()
            if job.workdir.resolve() not in path.parents or not path.is_file():
                continue
            stored[name] = job.store(conn, path, label=name)["id"]
        _finish(conn, job, {"result": result, "artifacts": stored})


LOCAL = {"check": run_check, "edit": run_edit, "pull": run_pull, "inspect": run_inspect, "frame": run_frame,
         "ffmpeg": run_ffmpeg}
