"""Provider-backed tasks: video, image, tts, music. Prepare a normalized request, run or submit it,
poll until the upstream job ends, then store files, entities, links and cost in one transaction."""

from __future__ import annotations

import time
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from .. import db, graph
from ..compose import compose
from ..media import MediaError, contact_sheet, frame_at, probe
from ..providers.base import InputError, Outcome, OutputFile, ProviderError, TransientError
from . import tasks as task_q
from .job import Canceled, Job

REF_TEXT = {
    "首帧": ("画面构图、主体位置和光线", "画面里多余的文字和标识"),
    "尾帧": ("结尾时的构图和主体位置", "画面里多余的文字和标识"),
    "身份": ("主体的外形、颜色和标识", "背景和光线"),
    "空间": ("场景布局和光线方向", "人物和动作"),
    "细节": ("这个物件的形状和材质", "背景和人物"),
    "风格": ("画面质感和调色", "具体的人物和场景"),
    "分镜": ("镜头的构图和景别", "画面里的具体细节"),
}
TRANSIENT_LIMIT = 20


class Park(Exception):
    """Stop and wait for a person. The provider reference stays on the task."""


def _resolution(job: Job, conn) -> str:
    if job.is_workflow:
        spec = job.spec(conn)
        return job.node.get("resolution") or (spec.get("defaults") or {}).get("resolution") or "768p横"
    return job.input.get("resolution") or "768p横"


def prepare_video(conn, job: Job) -> tuple[dict, dict]:
    graph_view = job.graph(conn)
    if job.is_workflow:
        scope = job.scope(conn)
        shot_id = job.input["item"]
        allow = bool(job.node.get("allow_warnings"))
        template = scope.asset_data(job.node["template"]) if job.node.get("template") else None
        override = job.node.get("prompt") if job.node.get("prompt") not in (None, "compose") else None
        prompt_override = scope.render(override) if override else None
        params = dict(job.node.get("params") or {})
    else:
        shot_id = job.input["shot_id"]
        allow = bool(job.input.get("allow_warnings"))
        template = None
        if job.input.get("template"):
            from .. import assets

            template = assets.resolve(conn, job.task["workspace_id"], job.input["template"])["data"]
        prompt_override = job.input.get("prompt")
        params = dict(job.input.get("params") or {})
    extra = []
    if job.input.get("prev_task"):
        previous = task_q.get(conn, job.input["prev_task"]) or {}
        frame = (previous.get("output") or {}).get("last_frame_artifact_id")
        if frame:
            extra.append({"id": frame, "type": "Reference", "artifact_id": frame, "data": {
                "title": "上一镜尾帧", "role": "空间", "take": "只采用画面里的空间和人物位置",
                "ignore": "不采用这一帧里已经结束的动作",
            }})
    resolution = _resolution(job, conn)
    plan = compose(graph_view, shot_id, resolution, extra_refs=extra)
    blocking = [item for item in plan["warnings"] if "不能提交" in item]
    if blocking or (plan["warnings"] and not allow):
        raise InputError("组合有警告，没有提交：" + "；".join(plan["warnings"]))
    references = []
    for ref in plan["references"]:
        if not ref.get("artifact_id"):
            raise InputError(f"参考 {ref['title']} 还没有文件")
        references.append({"path": job.local(conn, ref["artifact_id"]), "role": ref["role"]})
    request = {
        "prompt": prompt_override or plan["prompt"], "references": references, "duration": plan["duration"],
        "resolution": resolution, "template": template, "seed": params.pop("seed", None), "params": params,
    }
    task_q.patch_input(conn, job.id, {"request": {
        "template": job.node.get("template") or job.input.get("template") or "",
        "resolution": resolution,
        "duration": plan["duration"],
    }})
    shot = graph_view.get(shot_id)
    meta = {"shot_id": shot_id, "shot_title": shot["data"].get("title") or shot_id, "prompt": request["prompt"],
            "warnings": plan["warnings"], "references": [ref["title"] for ref in plan["references"]],
            "duration": plan["duration"], "resolution": resolution}
    return request, meta


def store_video(conn, job: Job, outcome: Outcome, meta: dict) -> dict:
    video = next((item for item in outcome.files if item.mime.startswith("video/")), None)
    if not video:
        raise ProviderError("供应商没有返回视频文件")
    artifact = job.store(conn, video.path, kind="video", label=f"{meta['shot_title']} 成片")
    sheet_path = job.workdir / "sheet.jpg"
    last_path = job.workdir / "last.jpg"
    output = {**meta, "artifact_id": artifact["id"], "duration": artifact["duration"]}
    try:
        info = probe(video.path)
        contact_sheet(video.path, sheet_path)
        frame_at(video.path, last_path, max(0.0, float(info["duration"] or 0) - 0.1))
        output["sheet_artifact_id"] = job.store(conn, sheet_path, kind="sheet", label="接触表")["id"]
        output["last_frame_artifact_id"] = job.store(conn, last_path, kind="frame", label="尾帧")["id"]
        output["probe"] = info
    except MediaError as exc:
        output["media_warning"] = str(exc)
    clip = graph.add_entity(conn, job.principal, job.task["work_id"], "Clip", {
        "title": f"{meta['shot_title']} 成片", "duration": artifact["duration"], "resolution": meta["resolution"],
    }, artifact_id=artifact["id"], run_id=job.task.get("run_id"))
    graph.add_link(conn, job.principal, job.task["work_id"], "clip_of", clip["id"], meta["shot_id"])
    output["clip_id"] = clip["id"]
    output.update({key: value for key, value in outcome.data.items() if key in {"upstream_status"}})
    return output


def prepare_image(conn, job: Job) -> tuple[dict, dict]:
    graph_view = job.graph(conn)
    if job.is_workflow:
        scope = job.scope(conn)
        prompt = scope.render(job.node["prompt"])
        role = job.node["role"]
        reference_ids = [artifact for template in job.node.get("references", []) for artifact in scope.artifacts(template)]
        count = int(job.node.get("candidates", 1))
        attach_to = scope.targets(job.node["attach_to"])[0] if job.node.get("attach_to") else None
        select_mode = job.node.get("select", "first")
        params = dict(job.node.get("params") or {})
    else:
        attach_to = job.input.get("shot_id")
        shot = graph_view.get(attach_to) if attach_to else None
        prompt = job.input.get("prompt") or ((shot or {}).get("data", {}).get("action") or "产品锚定图")
        role = job.input.get("role") or "细节"
        reference_ids = list(job.input.get("references") or [])
        count = int(job.input.get("n") or 1)
        select_mode = "first"
        params = dict(job.input.get("params") or {})
    title_base = graph_view.get(attach_to)["data"].get("title") if attach_to else "生图"
    request = {"prompt": prompt, "references": [job.local(conn, item) for item in reference_ids], "n": count,
               "params": params}
    return request, {"prompt": prompt, "role": role, "attach_to": attach_to, "select": select_mode,
                     "title": f"{title_base} {role}", "redraw_of": job.input.get("redraw_of")}


def store_image(conn, job: Job, outcome: Outcome, meta: dict) -> dict:
    images = [item for item in outcome.files if item.mime.startswith("image/")]
    if not images:
        raise ProviderError("供应商没有返回图片")
    take, ignore = REF_TEXT.get(meta["role"], ("画面中指定的部分", "其余内容"))
    candidates = []
    for index, image in enumerate(images):
        artifact = job.store(conn, image.path, kind="image", label=image.label or f"候选 {index + 1}")
        entity = graph.add_entity(conn, job.principal, job.task["work_id"], "Reference", {
            "title": meta["title"] if len(images) == 1 else f"{meta['title']} 候选 {index + 1}",
            "role": meta["role"], "take": take, "ignore": ignore,
        }, artifact_id=artifact["id"], run_id=job.task.get("run_id"))
        if meta.get("redraw_of"):
            graph.add_link(conn, job.principal, job.task["work_id"], "derived_from", entity["id"], meta["redraw_of"], "重新抽卡")
        candidates.append({"entity_id": entity["id"], "artifact_id": artifact["id"]})
    attached = None
    if meta["attach_to"] and meta["select"] == "first":
        attached = candidates[0]["entity_id"]
        graph.add_link(conn, job.principal, job.task["work_id"], "references", meta["attach_to"], attached, "生图入库")
    return {"candidates": candidates, "attach_to": meta["attach_to"], "attached": attached,
            "artifact_id": candidates[0]["artifact_id"], "prompt": meta["prompt"], "role": meta["role"]}


def prepare_tts(conn, job: Job) -> tuple[dict, dict]:
    graph_view = job.graph(conn)
    if job.is_workflow:
        scope = job.scope(conn)
        line_id = job.input["item"]
        voice_id = scope.targets(job.node["voice"])[0]
        text_value = scope.render(job.node.get("text") or "{{item.text}}")
    else:
        line_id = job.input["line_id"]
        voice_id = job.input["voice"]
        text_value = graph_view.get(line_id)["data"].get("text") or ""
    voice = graph_view.get(voice_id)
    speaker = voice.get("artifact_id")
    if not speaker and voice.get("kind") == "entity":
        speaker = next((ref.get("artifact_id") for ref in graph_view.linked(voice_id, "references")
                        if ref["data"].get("role") == "音色" and ref.get("artifact_id")), None)
    request = {"text": text_value, "voice": voice["data"], "speaker": job.local(conn, speaker) if speaker else None}
    return request, {"line_id": line_id, "title": graph_view.get(line_id)["data"].get("title") or "台词"}


def store_tts(conn, job: Job, outcome: Outcome, meta: dict) -> dict:
    audio = next((item for item in outcome.files if item.mime.startswith("audio/")), None)
    if not audio:
        raise ProviderError("供应商没有返回音频")
    artifact = job.store(conn, audio.path, kind="audio", label=f"{meta['title']} 配音")
    clip = graph.add_entity(conn, job.principal, job.task["work_id"], "Clip", {
        "title": f"{meta['title']} 配音", "duration": artifact["duration"],
    }, artifact_id=artifact["id"], run_id=job.task.get("run_id"))
    graph.add_link(conn, job.principal, job.task["work_id"], "line_of", clip["id"], meta["line_id"])
    return {"clip_id": clip["id"], "artifact_id": artifact["id"], "duration": artifact["duration"]}


def prepare_music(conn, job: Job) -> tuple[dict, dict]:
    if job.is_workflow:
        scope = job.scope(conn)
        prompt = scope.render(job.node["prompt"])
        lyrics = scope.render(job.node.get("lyrics") or "")
        duration = job.node.get("duration_seconds")
    else:
        prompt = job.input.get("prompt") or ""
        lyrics = job.input.get("lyrics") or ""
        duration = job.input.get("duration")
    if not (prompt or lyrics).strip():
        raise InputError("没有描述或歌词，不能生成音乐")
    return {"prompt": prompt, "lyrics": lyrics, "duration": duration}, {"title": (prompt or lyrics)[:30]}


def store_music(conn, job: Job, outcome: Outcome, meta: dict) -> dict:
    audio = next((item for item in outcome.files if item.mime.startswith("audio/")), None)
    if not audio:
        raise ProviderError("供应商没有返回音频")
    artifact = job.store(conn, audio.path, kind="audio", label=meta["title"] or "配乐")
    clip = graph.add_entity(conn, job.principal, job.task["work_id"], "Clip", {
        "title": meta["title"] or "配乐", "duration": artifact["duration"],
    }, artifact_id=artifact["id"], run_id=job.task.get("run_id"))
    return {"clip_id": clip["id"], "artifact_id": artifact["id"], "duration": artifact["duration"]}


PREPARE = {"video": prepare_video, "image": prepare_image, "tts": prepare_tts, "music": prepare_music}
STORE = {"video": store_video, "image": store_image, "tts": store_tts, "music": store_music}


def _check_device_budget(conn, job: Job, adapter, instance, request: dict) -> None:
    if job.task["created_by_kind"] != "device" or job.input.get("approved_by"):
        return
    from ..workflows.runner import spent_today

    limit = conn.execute(select(db.devices.c.daily_budget_yuan).where(db.devices.c.id == job.task["created_by_id"])).scalar()
    if limit is None:
        return
    estimate = sum(Decimal(str(instance.pricing.get(item.unit, 0))) * Decimal(str(item.quantity))
                   for item in adapter.estimate(request))
    spent = spent_today(conn, "device", job.task["created_by_id"])
    if spent + estimate > Decimal(str(limit)):
        raise Park(f"这台设备今天已花 {spent} 元，加上这次估算 {round(estimate, 2)} 元超过日预算 {limit} 元，需要审计员批准")


def _manual_outcome(conn, job: Job) -> Outcome | None:
    artifact_id = (job.task.get("output") or {}).get("manual_artifact_id")
    if not artifact_id:
        return None
    from .. import artifacts

    row = artifacts.get(conn, artifact_id)
    return Outcome(files=[OutputFile(job.local(conn, artifact_id), row["mime"], row["label"])],
                   data={"manual": True})


def run_provider(job: Job) -> None:
    from ..workflows.runner import record_cost, task_finished

    ctx = job.context()
    with db.tx() as conn:
        instance, adapter = job.adapter(conn)
        request, meta = PREPARE[job.task["kind"]](conn, job)
        outcome = _manual_outcome(conn, job)
        if outcome is None and not job.task.get("provider_ref"):
            _check_device_budget(conn, job, adapter, instance, request)
    if outcome is None:
        if adapter.sync:
            with db.tx() as conn:
                task_q.set_status(conn, job.id, "running")
            outcome = adapter.run(request, ctx)
        else:
            ref = job.task.get("provider_ref")
            if not ref and job.task.get("attempts", 0) > 1:
                ref = adapter.find(ctx)
            if not ref:
                with db.tx() as conn:
                    task_q.set_status(conn, job.id, "submitting")
                ref = {**adapter.submit(request, ctx), "_instance": instance.name}
                with db.tx() as conn:
                    task_q.set_status(conn, job.id, "submitted", provider_ref=ref, submitted_at=db.now())
                    job.task["submitted_at"] = db.now()
            job.task["provider_ref"] = ref
            outcome = _poll(job, adapter, ref)
    with db.tx(lock_run=job.task.get("run_id")) as conn:
        output = STORE[job.task["kind"]](conn, job, outcome, meta)
        cost = record_cost(conn, job.task, instance, outcome.usage)
        output["cost_yuan"] = float(cost)
        output["instance"] = instance.name
        if job.cancel_requested():
            task_q.mark_canceled(conn, job.id, output)
        else:
            task_q.complete(conn, job.id, output)
        task_finished(conn, job.task, job.principal)


def _poll(job: Job, adapter, ref: dict) -> Outcome:
    ctx = job.context()
    started = job.task.get("submitted_at") or db.now()
    deadline = started + timedelta(seconds=int(job.task.get("timeout_seconds") or 1800))
    failures = 0
    cancel_tried = False
    while True:
        if job.cancel_requested() and not cancel_tried:
            cancel_tried = True
            if adapter.cancel(ref, ctx):
                raise Canceled()
            job.logs.append("上游不能取消，继续等待，已扣费的结果仍会下载入库")
        try:
            result = adapter.poll(ref, ctx)
            failures = 0
        except TransientError as exc:
            failures += 1
            if failures >= TRANSIENT_LIMIT:
                raise Park(f"连续 {failures} 次查询失败：{exc}。上游任务号已保留，可重新查询") from exc
            time.sleep(min(adapter.poll_interval, 30))
            continue
        if isinstance(result, Outcome):
            return result
        with db.tx() as conn:
            task_q.set_progress(conn, job.id, result.fraction, result.message)
        if db.now() > deadline:
            if adapter.cancel(ref, ctx):
                raise ProviderError("超时，已取消上游任务")
            raise Park(f"超过 {job.task.get('timeout_seconds')} 秒仍未完成。上游任务号已保留，可在任务页重新查询")
        time.sleep(adapter.poll_interval)
