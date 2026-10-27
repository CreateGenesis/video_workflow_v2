"""Platform API. The agent process does not serve these routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from pydantic import BaseModel, Field

from cvplatform.comic import (
    apply_change,
    assign_slot,
    build_formal,
    check_g3,
    confirm,
    confirm_dialogue,
    create_episode,
    edit_seven,
    episode_row,
    graph_for,
    latest_probe,
    list_segments,
    asset_lock_text,
    lock_lines,
    mark_speakers,
    promote,
    prompt_errors,
    reprobe,
    search_products,
    set_one_action,
    start_published,
    submit_probe,
    submit_ratios,
)
from cvplatform.db import init_schema, session
from cvplatform.gates import (
    COMMANDS,
    GateError,
    can_generate_first_frame,
    command_before,
    concat_ready,
    forbid_reference_write,
    g4_checks_seam,
    may_export_ids,
    next_probe_allowed,
    probe_aspect_reference,
    require_price,
)
from cvplatform.jobs import accept_write_prompt, agent_insert_business, claim, complete, enqueue, inspect, reject_agent_insert
from cvplatform.probes import (
    judge_benchmark,
    may_create_segment_script,
    probe_h3,
    probe_image,
    probe_text,
    record_benchmark,
    verify_account,
    verify_mcp,
)

app = FastAPI(title="cvgen-platform", version="3.0.0")
PROCESS = "platform"


class JobIn(BaseModel):
    workspace_id: str
    type: str
    input: dict[str, Any]


class CompleteIn(BaseModel):
    owner: str
    output: dict[str, Any] | None = None
    error: str | None = None


class AcceptIn(BaseModel):
    valid: bool


class SegmentIn(BaseModel):
    number: int
    duration: float
    cast: list[str]
    scene: str
    action: str
    dialogue: str
    end_state: str


class PublishIn(BaseModel):
    version_id: str
    script: str = ""
    inspiration: str = ""


def _fail(exc: GateError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})


def _role(role: str) -> str:
    try:
        reject_agent_insert(role)
    except GateError as exc:
        raise _fail(exc) from exc
    return role


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_schema()
    _seed()
    yield


app.router.lifespan_context = lifespan


def _seed() -> None:
    from sqlalchemy import text

    with session() as db:
        db.execute(
            text(
                """
                INSERT INTO workflow_versions (id, name, protocol, pinned_json, published)
                VALUES ('wf_comic', '漫剧九步', 'video.autodl-h3', :pinned, 1)
                ON CONFLICT(id) DO NOTHING
                """
            ),
            {"pinned": '{"number_map":[{"asset_id":"role-a","kind":"角色","number":1}]}'},
        )
        db.execute(
            text(
                """
                INSERT INTO provider_instances (name, protocol, workflow_id, base_url, token, input_rules)
                VALUES ('video.autodl-h3', 'autodl-h3', 'minimax_h3_803', '', '', '{}')
                ON CONFLICT(name) DO NOTHING
                """
            )
        )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"process": PROCESS, "service": "platform-api"}


@app.post("/api/jobs")
def post_job(body: JobIn) -> dict[str, Any]:
    try:
        with session() as db:
            return enqueue(db, workspace_id=body.workspace_id, job_type=body.type, payload=body.input)
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/jobs/claim")
def post_claim(owner: str) -> dict[str, Any]:
    with session() as db:
        claimed = claim(db, owner, credential="cred-" + owner)
    if claimed is None:
        return {"claimed": False}
    return {"claimed": True, "credential_ttl_seconds": 600, "lease_ttl_seconds": 600, **claimed}


@app.post("/api/jobs/{job_id}/complete")
def post_complete(job_id: str, body: CompleteIn) -> dict[str, Any]:
    try:
        with session() as db:
            return complete(db, job_id, body.owner, body.output, body.error)
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/jobs/{job_id}/accept")
def post_accept(job_id: str, body: AcceptIn) -> dict[str, Any]:
    try:
        with session() as db:
            return accept_write_prompt(db, job_id, valid=body.valid)
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/jobs/inspect")
def post_inspect() -> dict[str, Any]:
    with session() as db:
        changed = inspect(db)
    return {"changed": changed}


@app.post("/api/agent/insert")
def post_agent_insert(role: str = "agent") -> dict[str, Any]:
    try:
        with session() as db:
            agent_insert_business(db, role)
    except GateError as exc:
        raise _fail(exc) from exc
    return {"ok": True}


@app.post("/api/episodes")
def post_episode(workspace_id: str = "ws", role: str = "platform") -> dict[str, str]:
    _role(role)
    with session() as db:
        return {"id": create_episode(db, workspace_id)}


@app.get("/api/episodes/{episode_id}/segments")
def get_segments(episode_id: str) -> dict[str, Any]:
    with session() as db:
        return {"items": list_segments(db, episode_id)}


@app.post("/api/episodes/{episode_id}/segments")
def post_segments(episode_id: str, rows: list[SegmentIn], dialogue_mode: str | None = None, role: str = "platform") -> dict[str, Any]:
    _role(role)
    try:
        with session() as db:
            from cvplatform.comic import save_segments

            saved = save_segments(
                db, episode_id, [row.model_dump() for row in rows], dialogue_mode
            )
        return {"items": saved}
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/episodes/{episode_id}/dialogue")
def post_dialogue(episode_id: str, mode: str) -> dict[str, str]:
    try:
        with session() as db:
            confirm_dialogue(db, episode_id, mode)
        return {"ok": "true"}
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/segments/{segment_id}/speakers")
def post_speakers(segment_id: str, speakers: list[str]) -> dict[str, str]:
    with session() as db:
        mark_speakers(db, segment_id, speakers)
    return {"ok": "true"}


@app.post("/api/segments/{segment_id}/one-action")
def post_one_action(segment_id: str, checked: bool = True) -> dict[str, str]:
    with session() as db:
        set_one_action(db, segment_id, checked)
    return {"ok": "true"}


@app.post("/api/segments/{segment_id}/confirm")
def post_confirm(segment_id: str) -> dict[str, Any]:
    try:
        with session() as db:
            return confirm(db, segment_id)
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/segments/{segment_id}/edit")
def post_edit(segment_id: str, changes: dict[str, Any], dialogue_mode: str | None = None) -> dict[str, Any]:
    try:
        with session() as db:
            return edit_seven(db, segment_id, changes, dialogue_mode)
    except GateError as exc:
        raise _fail(exc) from exc


class RatioIn(BaseModel):
    left: str
    right: str
    left_ratio: float
    right_ratio: float


@app.post("/api/episodes/{episode_id}/ratios")
def post_ratios(episode_id: str, pairs: list[RatioIn]) -> dict[str, str]:
    try:
        with session() as db:
            submit_ratios(db, episode_id, [pair.model_dump() for pair in pairs])
        return {"ok": "true"}
    except GateError as exc:
        raise _fail(exc) from exc


class SlotIn(BaseModel):
    asset_id: str
    kind: str
    number: int
    segment_id: str | None = None
    product_id: str | None = None
    empty: bool = False
    accepted: bool = True


@app.post("/api/episodes/{episode_id}/slots")
def post_slot(episode_id: str, body: SlotIn, role: str = "platform") -> dict[str, Any]:
    _role(role)
    try:
        with session() as db:
            return assign_slot(db, episode_id, **body.model_dump())
    except GateError as exc:
        raise _fail(exc) from exc


@app.get("/api/segments/{segment_id}/graph")
def get_graph(segment_id: str) -> dict[str, Any]:
    with session() as db:
        return {"items": graph_for(db, segment_id)}


@app.get("/api/assets/{asset_id}/lock")
def get_asset_lock(asset_id: str) -> dict[str, Any]:
    with session() as db:
        return {"lock_text": asset_lock_text(db, asset_id)}


@app.get("/api/products")
def get_products(q: str = "") -> dict[str, Any]:
    with session() as db:
        return {"items": search_products(db, q)}


class PromoteIn(BaseModel):
    kind: str
    lock_text: str


@app.post("/api/products/{product_id}/promote")
def post_promote(product_id: str, body: PromoteIn, role: str = "platform") -> dict[str, Any]:
    _role(role)
    try:
        with session() as db:
            return promote(db, product_id, body.kind, body.lock_text)
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/runs")
def post_run(body: PublishIn) -> dict[str, Any]:
    if body.inspiration and not body.script:
        raise HTTPException(status_code=422, detail={"code": "inspiration", "message": "一句灵感不能直接出片"})
    try:
        with session() as db:
            return start_published(db, body.version_id, body.script)
    except GateError as exc:
        raise _fail(exc) from exc


@app.get("/api/comic/missing")
def missing(episode_id: str) -> dict[str, Any]:
    with session() as db:
        try:
            episode = episode_row(db, episode_id)
        except GateError as exc:
            raise _fail(exc) from exc
        segments = list_segments(db, episode_id)
    gaps = []
    if not episode.get("dialogue_confirmed"):
        gaps.append("是否对白")
    if not segments:
        gaps.append("分段表")
    elif any(not item["confirmed"] for item in segments):
        gaps.append("确认分段")
    step = gaps[0] if gaps else "通过"
    return {
        "process": PROCESS,
        "stopped_at": step,
        "missing": gaps,
        "local_h3": False,
    }


@app.post("/api/segments/{segment_id}/probe")
def post_probe(segment_id: str, resolution: str, mode: str, duration: float, seed: str, audio_binding: str = "", rules: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        with session() as db:
            opened = submit_probe(
                db,
                segment_id,
                resolution=resolution,
                mode=mode,
                duration=duration,
                rules=rules or {},
                seed=seed,
                audio_binding=audio_binding,
            )
            current = db.execute(text("SELECT duration FROM segments WHERE id = :id"), {"id": segment_id}).first()
        opened["segment_duration"] = current[0]
        opened["aspect_reference"] = probe_aspect_reference(resolution)
        return opened
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/segments/{segment_id}/reprobe")
def post_reprobe(segment_id: str) -> dict[str, Any]:
    try:
        with session() as db:
            return reprobe(db, segment_id)
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/probe-results/{result_id}/check")
def post_check(result_id: str) -> dict[str, str]:
    with session() as db:
        check_g3(db, result_id)
    return {"ok": "true"}


@app.post("/api/segments/{segment_id}/formal")
def post_formal(segment_id: str) -> dict[str, Any]:
    try:
        with session() as db:
            return build_formal(db, segment_id)
    except GateError as exc:
        raise _fail(exc) from exc


@app.get("/api/rerun")
def get_rerun(change: str, has_next: bool = False) -> dict[str, Any]:
    try:
        return apply_change(change, has_next=has_next)
    except GateError as exc:
        raise _fail(exc) from exc


class PromptCheck(BaseModel):
    full_text: str
    slots: list[dict[str, Any]]
    sections: dict[str, str]
    duration: float


@app.post("/api/prompts/validate")
def post_validate(body: PromptCheck) -> dict[str, Any]:
    errors = prompt_errors(body.full_text, body.slots, body.sections, body.duration)
    return {"ok": not errors, "errors": errors, "lines": lock_lines(body.slots)}


@app.post("/api/probes/text")
def post_probe_text(base_url: str, token: str = "") -> dict[str, Any]:
    return probe_text(base_url, token)


@app.post("/api/probes/image")
def post_probe_image(base_url: str, token: str = "") -> dict[str, Any]:
    return probe_image(base_url, token)


@app.post("/api/probes/h3")
def post_probe_h3(base_url: str, token: str, workflow_id: str) -> dict[str, Any]:
    try:
        return probe_h3(base_url, token, workflow_id)
    except GateError as exc:
        raise _fail(exc) from exc


class AccountIn(BaseModel):
    fields: dict[str, str]
    example: str


@app.post("/api/accounts/verify")
def post_account(body: AccountIn) -> dict[str, Any]:
    return verify_account(body.fields, body.example, checker=lambda fields: None if fields else (_ for _ in ()).throw(RuntimeError("empty")))


class McpIn(BaseModel):
    address: str
    tools: list[str] = Field(default_factory=list)
    fail: str = ""


@app.post("/api/mcp/verify")
def post_mcp(body: McpIn) -> dict[str, Any]:
    def handshake(_address: str) -> list[str]:
        if body.fail:
            raise RuntimeError(body.fail)
        return body.tools

    return verify_mcp({"address": body.address}, handshake=handshake)


@app.get("/api/segment-script/allowed")
def segment_allowed(needs_external: bool = False, mcp_status: str | None = None) -> dict[str, bool]:
    return {"allowed": may_create_segment_script(needs_external=needs_external, mcp_status=mcp_status)}


@app.get("/api/boot")
def boot() -> dict[str, Any]:
    from sqlalchemy import text

    with session() as db:
        names = [row[0] for row in db.execute(text("SELECT name FROM provider_instances")).all()]
    return {"providers": names, "comfy": [name for name in names if "comfy" in name]}


@app.post("/api/works/{work_id}/entities")
def post_entity(work_id: str) -> dict[str, Any]:
    try:
        forbid_reference_write()
    except GateError as exc:
        raise _fail(exc) from exc
    return {"id": work_id}


@app.get("/api/commands")
def get_commands() -> dict[str, Any]:
    return {
        "order": COMMANDS,
        "g1_before_image": command_before("勾选 G1", "触发生图"),
        "g2_before_probe": command_before("勾选 G2", "提交探针"),
        "g3_after_probe": command_before("提交探针", "勾选 G3"),
        "ratio_after_segments": command_before("提交分段", "提交同框比例"),
    }


class FrameAllow(BaseModel):
    g1: str
    speakers: list[str]
    voices: list[str]


@app.post("/api/first-frame/allowed")
def first_frame_allowed(body: FrameAllow) -> dict[str, bool]:
    try:
        can_generate_first_frame(body.g1, body.speakers, body.voices)
    except GateError as exc:
        raise _fail(exc) from exc
    return {"allowed": True}


@app.get("/api/segments/{segment_id}/g4")
def g4_rule(segment_id: str, number: int) -> dict[str, Any]:
    return {"segment_id": segment_id, "checks_seam": g4_checks_seam(number)}


class ConcatIn(BaseModel):
    segments: list[dict[str, Any]]
    episode: dict[str, Any]


@app.post("/api/concat/ready")
def post_concat(body: ConcatIn) -> dict[str, Any]:
    try:
        return concat_ready(body.segments, body.episode)
    except GateError as exc:
        raise _fail(exc) from exc


@app.post("/api/estimate")
def post_estimate(kind: str, unit_price: float | None = None, quantity: float = 1) -> dict[str, float]:
    try:
        price = require_price(kind, unit_price)
    except GateError as exc:
        raise _fail(exc) from exc
    return {"amount": price * quantity}


@app.post("/api/segments/{segment_id}/next-probe")
def post_next_probe(segment_id: str, last_frame_slotted: bool) -> dict[str, Any]:
    try:
        next_probe_allowed(last_frame_slotted)
    except GateError as exc:
        raise _fail(exc) from exc
    return {"segment_id": segment_id, "allowed": True}


@app.post("/api/backfill/export")
def post_export(process_stopped: bool) -> dict[str, bool]:
    try:
        may_export_ids(process_stopped)
    except GateError as exc:
        raise _fail(exc) from exc
    return {"allowed": True}


@app.get("/api/episodes/{episode_id}")
def get_episode(episode_id: str) -> dict[str, Any]:
    try:
        with session() as db:
            episode = episode_row(db, episode_id)
            episode["segments"] = list_segments(db, episode_id)
            episode["numbers"] = [
                dict(row)
                for row in db.execute(text("SELECT asset_id, kind, number FROM number_maps WHERE episode_id = :id"), {"id": episode_id}).mappings()
            ]
        return episode
    except GateError as exc:
        raise _fail(exc) from exc


def main() -> None:
    import uvicorn

    port = int(os.environ.get("CVGEN_PLATFORM_PORT", "8093"))
    uvicorn.run("cvplatform.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
