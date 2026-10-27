"""Episode state machine. Slot assignment, confirm, and video ingest are platform commands."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from cvplatform.gates import (
    GateError,
    character_slots,
    check_ratios,
    concat_ready,
    confirm_segment,
    copy_probe_fields,
    formal_submit_body,
    mark_failed,
    probe_spec,
    promote_allowed,
    recheck_dialogue_change,
    rerun,
    save_segment_row,
    subject_lines,
    used_keep,
    validate_prompt,
)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def create_episode(session: Session, workspace_id: str, workflow_version_id: str | None = None) -> str:
    episode_id = "ep_" + uuid.uuid4().hex[:12]
    session.execute(
        text("INSERT INTO episodes (id, workspace_id, workflow_version_id, script) VALUES (:id, :workspace_id, :version, '')"),
        {"id": episode_id, "workspace_id": workspace_id, "version": workflow_version_id},
    )
    return episode_id


def save_segments(session: Session, episode_id: str, rows: list[dict[str, Any]], dialogue_mode: str | None) -> list[dict[str, Any]]:
    saved = []
    for row in rows:
        item = save_segment_row({**row, "dialogue_mode": dialogue_mode})
        segment_id = "seg_" + uuid.uuid4().hex[:12]
        session.execute(
            text(
                """
                INSERT INTO segments (
                  id, episode_id, number, duration, cast_json, scene, action, dialogue, end_state, confirmed
                ) VALUES (
                  :id, :episode_id, :number, :duration, :cast_json, :scene, :action, :dialogue, :end_state, 0
                )
                """
            ),
            {
                "id": segment_id,
                "episode_id": episode_id,
                "number": item["number"],
                "duration": item["duration"],
                "cast_json": _dumps(item["cast"]),
                "scene": item["scene"],
                "action": item["action"],
                "dialogue": item["dialogue"],
                "end_state": item["end_state"],
            },
        )
        saved.append({"id": segment_id, **item})
    return saved


def list_segments(session: Session, episode_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text("SELECT * FROM segments WHERE episode_id = :id ORDER BY number"),
        {"id": episode_id},
    ).mappings().all()
    out = []
    for row in rows:
        item = dict(row)
        item["cast"] = _loads(item.pop("cast_json"), [])
        item["speakers"] = _loads(item.pop("speakers_json"), [])
        item["confirmed"] = bool(item["confirmed"])
        item["one_action_checked"] = bool(item["one_action_checked"])
        item["prompt_accepted"] = bool(item["prompt_accepted"])
        out.append(item)
    return out


def episode_row(session: Session, episode_id: str) -> dict[str, Any]:
    row = session.execute(text("SELECT * FROM episodes WHERE id = :id"), {"id": episode_id}).mappings().first()
    if row is None:
        raise GateError("missing", "没有这一集")
    item = dict(row)
    item["dialogue_confirmed"] = bool(item["dialogue_confirmed"])
    return item


def confirm_dialogue(session: Session, episode_id: str, mode: str) -> None:
    if mode not in {"有", "无"}:
        raise GateError("dialogue", "是否对白只能是有或无")
    session.execute(
        text("UPDATE episodes SET dialogue_mode = :mode, dialogue_confirmed = 1 WHERE id = :id"),
        {"mode": mode, "id": episode_id},
    )
    segments = list_segments(session, episode_id)
    for segment in recheck_dialogue_change(segments, mode):
        if not segment["confirmed"] or segment.get("g1") == "pending":
            session.execute(
                text("UPDATE segments SET confirmed = 0 WHERE id = :id"),
                {"id": segment["id"]},
            )
            session.execute(
                text("UPDATE episodes SET g1 = 'pending' WHERE id = :id"),
                {"id": episode_id},
            )


def mark_speakers(session: Session, segment_id: str, speakers: list[str]) -> None:
    session.execute(
        text("UPDATE segments SET speakers_json = :speakers WHERE id = :id"),
        {"speakers": _dumps(speakers), "id": segment_id},
    )


def edit_seven(session: Session, segment_id: str, changes: dict[str, Any], dialogue_mode: str | None) -> dict[str, Any]:
    current = session.execute(text("SELECT * FROM segments WHERE id = :id"), {"id": segment_id}).mappings().first()
    if current is None:
        raise GateError("missing", "没有这一段")
    row = {
        "number": current["number"],
        "duration": current["duration"],
        "cast": _loads(current["cast_json"], []),
        "scene": current["scene"],
        "action": current["action"],
        "dialogue": current["dialogue"],
        "end_state": current["end_state"],
    }
    row.update(changes)
    saved = save_segment_row({**row, "dialogue_mode": dialogue_mode})
    session.execute(
        text(
            """
            UPDATE segments
            SET duration = :duration, cast_json = :cast_json, scene = :scene, action = :action,
                dialogue = :dialogue, end_state = :end_state, confirmed = 0, prompt_accepted = 0
            WHERE id = :id
            """
        ),
        {
            "id": segment_id,
            "duration": saved["duration"],
            "cast_json": _dumps(saved["cast"]),
            "scene": saved["scene"],
            "action": saved["action"],
            "dialogue": saved["dialogue"],
            "end_state": saved["end_state"],
        },
    )
    return saved


def confirm(session: Session, segment_id: str) -> dict[str, Any]:
    current = session.execute(text("SELECT * FROM segments WHERE id = :id"), {"id": segment_id}).mappings().first()
    if current is None:
        raise GateError("missing", "没有这一段")
    episode = episode_row(session, current["episode_id"])
    segment = {
        "number": current["number"],
        "duration": current["duration"],
        "cast": _loads(current["cast_json"], []),
        "scene": current["scene"],
        "action": current["action"],
        "dialogue": current["dialogue"],
        "end_state": current["end_state"],
        "speakers": _loads(current["speakers_json"], []),
        "one_action_checked": bool(current["one_action_checked"]),
    }
    confirmed = confirm_segment(segment, episode)
    session.execute(text("UPDATE segments SET confirmed = 1 WHERE id = :id"), {"id": segment_id})
    return confirmed


def set_one_action(session: Session, segment_id: str, checked: bool) -> None:
    session.execute(
        text("UPDATE segments SET one_action_checked = :checked WHERE id = :id"),
        {"checked": 1 if checked else 0, "id": segment_id},
    )


def submit_ratios(session: Session, episode_id: str, pairs: list[dict[str, Any]]) -> None:
    segments = list_segments(session, episode_id)
    check_ratios(segments, pairs)
    session.execute(text("DELETE FROM ratios WHERE episode_id = :id"), {"id": episode_id})
    for pair in pairs:
        session.execute(
            text(
                """
                INSERT INTO ratios (id, episode_id, left_role, right_role, left_ratio, right_ratio)
                VALUES (:id, :episode_id, :left_role, :right_role, :left_ratio, :right_ratio)
                """
            ),
            {
                "id": "ratio_" + uuid.uuid4().hex[:10],
                "episode_id": episode_id,
                "left_role": pair["left"],
                "right_role": pair["right"],
                "left_ratio": pair["left_ratio"],
                "right_ratio": pair["right_ratio"],
            },
        )


def assign_slot(session: Session, episode_id: str, *, asset_id: str, kind: str, number: int, segment_id: str | None = None, product_id: str | None = None, empty: bool = False, accepted: bool = True) -> dict[str, Any]:
    from cvplatform.gates import reject_unaccepted_frame

    if not empty:
        reject_unaccepted_frame(kind, accepted)
    maps = session.execute(
        text("SELECT * FROM number_maps WHERE episode_id = :id"),
        {"id": episode_id},
    ).mappings().all()
    existing = [dict(row) for row in maps]
    fixed = None
    for row in existing:
        if row["asset_id"] == asset_id:
            fixed = row["number"]
            if number != fixed:
                raise GateError("number", "同一编号不能换资产")
    if fixed is None:
        for row in existing:
            if row["number"] == number and row["kind"] == kind:
                raise GateError("number", "同一编号不能换资产")
        session.execute(
            text(
                """
                INSERT INTO number_maps (id, episode_id, asset_id, kind, number)
                VALUES (:id, :episode_id, :asset_id, :kind, :number)
                """
            ),
            {
                "id": "map_" + uuid.uuid4().hex[:10],
                "episode_id": episode_id,
                "asset_id": asset_id,
                "kind": kind,
                "number": number,
            },
        )
    slot_id = "slot_" + uuid.uuid4().hex[:10]
    session.execute(
        text(
            """
            INSERT INTO slots (id, episode_id, segment_id, kind, number, asset_id, product_id, empty)
            VALUES (:id, :episode_id, :segment_id, :kind, :number, :asset_id, :product_id, :empty)
            """
        ),
        {
            "id": slot_id,
            "episode_id": episode_id,
            "segment_id": segment_id,
            "kind": kind,
            "number": number,
            "asset_id": asset_id,
            "product_id": product_id,
            "empty": 1 if empty else 0,
        },
    )
    if kind != "首帧":
        session.execute(
            text(
                """
                INSERT INTO graph_nodes (id, episode_id, segment_id, kind, label)
                VALUES (:id, :episode_id, :segment_id, :kind, :label)
                """
            ),
            {
                "id": "node_" + uuid.uuid4().hex[:8],
                "episode_id": episode_id,
                "segment_id": segment_id or "",
                "kind": kind,
                "label": f"{kind}:{number}",
            },
        )
    binding = character_slots(number) if kind == "角色" else {}
    return {"id": slot_id, "number": number, "binding": binding}


def graph_for(session: Session, segment_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text("SELECT kind, label FROM graph_nodes WHERE segment_id = :id"),
        {"id": segment_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def start_published(session: Session, version_id: str, script: str) -> dict[str, Any]:
    version = session.execute(
        text("SELECT * FROM workflow_versions WHERE id = :id"),
        {"id": version_id},
    ).mappings().first()
    if version is None:
        raise GateError("missing", "没有这个发布版")
    if "comfyui" in (version["protocol"] or "").lower() or "comfy" in (version["name"] or "").lower():
        raise GateError("removed_protocol", "该版本使用已移除的视频协议，请另存一版")
    if version["name"] != "漫剧九步":
        raise GateError("workflow", "网页新运行和 API v1 都只能提交九步漫剧工作流")
    if not script.strip():
        raise GateError("script", "没有剧本就不创建这条任务")
    episode_id = create_episode(session, "ws", version_id)
    session.execute(text("UPDATE episodes SET script = :script WHERE id = :id"), {"script": script, "id": episode_id})
    from cvplatform.jobs import enqueue

    pinned = _loads(version["pinned_json"], {})
    for item in pinned.get("number_map") or []:
        session.execute(
            text(
                """
                INSERT INTO number_maps (id, episode_id, asset_id, kind, number)
                VALUES (:id, :episode_id, :asset_id, :kind, :number)
                """
            ),
            {
                "id": "map_" + uuid.uuid4().hex[:10],
                "episode_id": episode_id,
                "asset_id": item["asset_id"],
                "kind": item["kind"],
                "number": item["number"],
            },
        )
    return {
        "episode_id": episode_id,
        "job_id": None,
        "submitted": True,
        "copied_segments": 0,
        "copied": False,
        "reallocated": False,
    }


def accept_published(session: Session, episode_id: str) -> dict[str, Any]:
    """The published episode creates segment_script only after the submitted version is accepted."""
    episode = episode_row(session, episode_id)
    if not str(episode.get("script") or "").strip():
        raise GateError("script", "没有剧本就不创建这条任务")
    if not episode.get("workflow_version_id"):
        raise GateError("workflow", "只有提交过的发布版才创建分段任务")
    existing = session.execute(
        text("SELECT id FROM jobs WHERE type = 'segment_script' AND input LIKE :needle"),
        {"needle": f"%{episode_id}%"},
    ).first()
    if existing:
        return {"episode_id": episode_id, "job_id": existing[0], "created": False}
    from cvplatform.jobs import enqueue

    job = enqueue(
        session,
        workspace_id=episode["workspace_id"],
        job_type="segment_script",
        payload={"script": episode["script"], "episode_id": episode_id},
    )
    return {"episode_id": episode_id, "job_id": job["id"], "created": True}


def accept_segment_script(session: Session, episode_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    episode = episode_row(session, episode_id)
    pending = session.execute(
        text("SELECT id, status FROM jobs WHERE type = 'segment_script' AND input LIKE :needle"),
        {"needle": f"%{episode_id}%"},
    ).mappings().first()
    if pending is None or pending["status"] != "succeeded":
        raise GateError("accept", "分段任务被接受后才保存分段表")
    return save_segments(session, episode_id, rows, episode.get("dialogue_mode"))


def submit_probe(session: Session, segment_id: str, *, resolution: str, mode: str, duration: float, rules: dict[str, Any], seed: str, audio_binding: str = "") -> dict[str, Any]:
    from cvplatform.gates import old_first_frame_blocks, reject_wrong_character_audio

    if not seed:
        raise GateError("seed", "没有 seed 就拒绝探针")
    current = session.execute(text("SELECT * FROM segments WHERE id = :id"), {"id": segment_id}).mappings().first()
    if current is None:
        raise GateError("missing", "没有这一段")
    if not current["prompt_accepted"] and current["prompt"]:
        raise GateError("prompt", "旧提示词不能进入探针")
    first = session.execute(
        text("SELECT empty, product_id FROM slots WHERE segment_id = :id AND kind = '首帧'"),
        {"id": segment_id},
    ).mappings().first()
    if first is None or first["empty"] or not first["product_id"]:
        raise GateError("slot", "ref_image_0 为空不能探针")
    if current["g2"] != "passed":
        raise GateError("g2", "勾选 G2 在首帧入槽之后、探针之前")
    stale = session.execute(
        text(
            """
            SELECT slots.id
            FROM slots
            JOIN asset_versions ON asset_versions.id = slots.asset_version_id
            JOIN assets ON assets.id = slots.asset_id
            WHERE slots.segment_id = :id
              AND slots.kind = '首帧'
              AND assets.kind IN ('角色', '场景', '道具')
              AND asset_versions.version < (
                SELECT MAX(version) FROM asset_versions newer WHERE newer.asset_id = slots.asset_id
              )
            """
        ),
        {"id": segment_id},
    ).first()
    old_first_frame_blocks(stale is not None)
    reject_wrong_character_audio(audio_binding)
    saved = probe_spec(resolution, mode, duration, rules)
    session.execute(
        text(
            """
            INSERT INTO probe_specs (id, segment_id, resolution, mode, duration)
            VALUES (:id, :segment_id, :resolution, :mode, :duration)
            """
        ),
        {"id": "ps_" + uuid.uuid4().hex[:8], "segment_id": segment_id, **saved},
    )
    session.execute(text("UPDATE probe_results SET superseded = 1, g3 = 'pending' WHERE segment_id = :id"), {"id": segment_id})
    result_id = "pr_" + uuid.uuid4().hex[:8]
    session.execute(
        text(
            """
            INSERT INTO probe_results (id, segment_id, created_at, g3, superseded)
            VALUES (:id, :segment_id, :created_at, 'pending', 0)
            """
        ),
        {"id": result_id, "segment_id": segment_id, "created_at": "now"},
    )
    session.execute(text("UPDATE segments SET seed = :seed WHERE id = :id"), {"seed": seed, "id": segment_id})
    return {"spec": saved, "result_id": result_id}


def reprobe(session: Session, segment_id: str) -> dict[str, Any]:
    saved = session.execute(
        text("SELECT resolution, mode, duration FROM probe_specs WHERE segment_id = :id ORDER BY id DESC"),
        {"id": segment_id},
    ).mappings().first()
    fields = copy_probe_fields(dict(saved) if saved else None)
    session.execute(text("UPDATE probe_results SET superseded = 1 WHERE segment_id = :id"), {"id": segment_id})
    result_id = "pr_" + uuid.uuid4().hex[:8]
    session.execute(
        text("INSERT INTO probe_results (id, segment_id, created_at, g3, superseded) VALUES (:id, :segment_id, 'now', 'pending', 0)"),
        {"id": result_id, "segment_id": segment_id},
    )
    return {"copied": fields, "result_id": result_id, "includes_seed": False, "includes_check": False, "includes_first_frame": False}


def check_g3(session: Session, result_id: str) -> None:
    session.execute(text("UPDATE probe_results SET g3 = 'passed' WHERE id = :id"), {"id": result_id})


def latest_probe(session: Session, segment_id: str) -> dict[str, Any] | None:
    row = session.execute(
        text("SELECT * FROM probe_results WHERE segment_id = :id AND superseded = 0 ORDER BY id DESC"),
        {"id": segment_id},
    ).mappings().first()
    return dict(row) if row else None


def build_formal(session: Session, segment_id: str) -> dict[str, Any]:
    current = session.execute(text("SELECT * FROM segments WHERE id = :id"), {"id": segment_id}).mappings().first()
    if current is None:
        raise GateError("missing", "没有这一段")
    episode = episode_row(session, current["episode_id"])
    slots = [
        dict(row)
        for row in session.execute(
            text("SELECT * FROM slots WHERE episode_id = :id AND (segment_id = :segment OR segment_id IS NULL)"),
            {"id": current["episode_id"], "segment": segment_id},
        ).mappings().all()
    ]
    for slot in slots:
        slot["empty"] = bool(slot["empty"])
        slot["file"] = slot.get("product_id") or ""
    probe = latest_probe(session, segment_id) or {}
    body = formal_submit_body(
        {
            "prompt": current["prompt"],
            "prompt_accepted": bool(current["prompt_accepted"]),
            "seed": current["seed"],
            "duration": current["duration"],
            "aspect": episode.get("aspect") or "1088x1920",
            "mode": episode.get("mode") or "高质",
            "latest_probe": {"g3": probe.get("g3")},
        },
        slots,
    )
    spec = session.execute(
        text("SELECT resolution, mode, duration FROM probe_specs WHERE segment_id = :id"),
        {"id": segment_id},
    ).mappings().first()
    if spec and body["duration"] == spec["duration"] and float(spec["duration"]) != float(current["duration"]):
        raise GateError("probe_leak", "正式提交不读探针保存的三项")
    body["read_probe_fields"] = False
    return body


def mark_g2(session: Session, segment_id: str, passed: bool) -> dict[str, Any]:
    current = session.execute(text("SELECT id FROM segments WHERE id = :id"), {"id": segment_id}).first()
    if current is None:
        raise GateError("missing", "没有这一段")
    first = session.execute(
        text("SELECT id FROM slots WHERE segment_id = :id AND kind = '首帧' AND empty = 0 AND product_id IS NOT NULL"),
        {"id": segment_id},
    ).first()
    if first is None:
        raise GateError("slot", "勾选 G2 在首帧入槽之后")
    value = "passed" if passed else "pending"
    session.execute(text("UPDATE segments SET g2 = :g2 WHERE id = :id"), {"g2": value, "id": segment_id})
    return {"id": segment_id, "g2": value}


def mark_qc(session: Session, segment_id: str, passed: bool) -> dict[str, Any]:
    """G4 is written by the QC command. Concat reads this stored column."""
    current = session.execute(text("SELECT id FROM segments WHERE id = :id"), {"id": segment_id}).first()
    if current is None:
        raise GateError("missing", "没有这一段")
    value = "passed" if passed else "pending"
    session.execute(text("UPDATE segments SET g4 = :g4 WHERE id = :id"), {"g4": value, "id": segment_id})
    return {"id": segment_id, "g4": value}


def bump_image_version(session: Session, asset_id: str, segment_id: str) -> dict[str, Any]:
    """A character, scene, or prop image bump clears G2. The old first frame stays slotted."""
    asset = session.execute(text("SELECT kind FROM assets WHERE id = :id"), {"id": asset_id}).mappings().first()
    if asset is None or asset["kind"] not in {"角色", "场景", "道具"}:
        raise GateError("version", "只升角色、场景或道具的图像版本才作废 G2")
    current = session.execute(
        text("SELECT COALESCE(MAX(version), 0) FROM asset_versions WHERE asset_id = :id"),
        {"id": asset_id},
    ).first()
    version = int(current[0]) + 1
    version_id = "ver_" + uuid.uuid4().hex[:8]
    session.execute(
        text("INSERT INTO asset_versions (id, asset_id, version, lock_text, accepted) VALUES (:id, :asset_id, :version, '', 1)"),
        {"id": version_id, "asset_id": asset_id, "version": version},
    )
    session.execute(text("UPDATE segments SET g2 = 'pending', g4 = 'pending' WHERE id = :id"), {"id": segment_id})
    return {"asset_id": asset_id, "version": version, "g2": "pending"}


def concat_episode(session: Session, episode_id: str) -> dict[str, Any]:
    episode = episode_row(session, episode_id)
    rows = session.execute(
        text("SELECT number, duration, g4 FROM segments WHERE episode_id = :id ORDER BY number"),
        {"id": episode_id},
    ).mappings().all()
    if not rows:
        raise GateError("g4", "每段 G4 都通过后才拼接")
    return concat_ready([dict(row) for row in rows], episode)


def apply_change(session: Session, segment_id: str, change: str, *, has_next: bool = False) -> dict[str, Any]:
    plan = mark_failed() if change == "failed" else rerun(change, has_next=has_next)
    if "g3" in plan.get("invalidate", []):
        session.execute(text("UPDATE probe_results SET g3 = 'pending', superseded = 1 WHERE segment_id = :id"), {"id": segment_id})
    if "g4" in plan.get("invalidate", []):
        session.execute(text("UPDATE segments SET g4 = 'pending' WHERE id = :id"), {"id": segment_id})
    if "g2" in plan.get("invalidate", []):
        session.execute(text("UPDATE segments SET g2 = 'pending' WHERE id = :id"), {"id": segment_id})
    stored = session.execute(text("SELECT g2, g4 FROM segments WHERE id = :id"), {"id": segment_id}).mappings().first()
    plan["stored"] = dict(stored) if stored else {}
    return plan


def prompt_errors(full_text: str, slots: list[dict[str, Any]], sections: dict[str, str], duration: float) -> list[str]:
    return validate_prompt(full_text, slots, sections, duration)


def lock_lines(slots: list[dict[str, Any]]) -> list[str]:
    return subject_lines(slots)


def asset_lock_text(session: Session, asset_id: str) -> str | None:
    row = session.execute(
        text("SELECT lock_text FROM asset_versions WHERE asset_id = :id ORDER BY version DESC"),
        {"id": asset_id},
    ).first()
    return None if row is None else row[0]


def search_products(session: Session, query: str) -> list[dict[str, Any]]:
    rows = session.execute(
        text("SELECT * FROM products WHERE prompt LIKE :q AND status = 'succeeded' ORDER BY created_at"),
        {"q": f"%{query}%"},
    ).mappings().all()
    return [dict(row) for row in rows]


def promote(session: Session, product_id: str, kind: str, lock_text: str) -> dict[str, Any]:
    if not promote_allowed(kind):
        raise GateError("promote", "首帧、同框比例图和成片末帧不能提升")
    product = session.execute(text("SELECT * FROM products WHERE id = :id"), {"id": product_id}).mappings().first()
    if product is None or not product["accepted"]:
        raise GateError("promote", "未验收的生图不在素材库")
    asset_id = "asset_" + uuid.uuid4().hex[:8]
    session.execute(
        text("INSERT INTO assets (id, workspace_id, name, kind, kept) VALUES (:id, :workspace_id, :name, :kind, 1)"),
        {"id": asset_id, "workspace_id": product["workspace_id"], "name": product["title"], "kind": kind},
    )
    session.execute(
        text("INSERT INTO asset_versions (id, asset_id, version, lock_text, accepted) VALUES (:id, :asset_id, 1, :lock_text, 1)"),
        {"id": "ver_" + uuid.uuid4().hex[:8], "asset_id": asset_id, "lock_text": lock_text},
    )
    session.execute(text("UPDATE products SET asset_id = :asset_id WHERE id = :id"), {"asset_id": asset_id, "id": product_id})
    return {"asset_id": asset_id, "lock_text": lock_text}


def backfill_decision(*, task_input: bool, clip_chain: bool, asset_link: bool, promoted: bool) -> str:
    return "keep" if used_keep(task_input, clip_chain, asset_link, promoted) else "soft_delete"


def run_backfill(session: Session, work_id: str, entity_ids: list[str]) -> dict[str, Any]:
    """Soft-delete listed references on one work. A promoted asset stays in the library."""
    kept = []
    removed = []
    for entity_id in entity_ids:
        asset = session.execute(text("SELECT * FROM assets WHERE id = :id"), {"id": entity_id}).mappings().first()
        promoted = asset is not None and bool(asset["kept"]) and asset["kind"] != "Reference"
        decision = backfill_decision(task_input=False, clip_chain=False, asset_link=False, promoted=promoted)
        if decision == "keep":
            kept.append(entity_id)
            continue
        session.execute(
            text("UPDATE assets SET kept = 0 WHERE id = :id AND kind = 'Reference'"),
            {"id": entity_id},
        )
        removed.append(entity_id)
    library = session.execute(
        text("SELECT id, name FROM assets WHERE kept = 1 AND kind != 'Reference' ORDER BY name"),
    ).mappings().all()
    return {"kept": kept, "removed": removed, "library": [dict(row) for row in library]}
