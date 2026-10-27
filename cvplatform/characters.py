"""Characters arrive complete from cvgen. The platform stores them and never designs them."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from cvplatform.gates import GateError
from cvplatform.jobs import enqueue

IMAGE_LIMIT = 9


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _character(session: Session, character_id: str) -> dict[str, Any]:
    row = session.execute(text("SELECT * FROM characters WHERE id = :id"), {"id": character_id}).mappings().first()
    if row is None:
        raise GateError("missing", "没有这个人物")
    item = dict(row)
    item["images"] = _loads(item.pop("images_json"), [])
    item["revision"] = int(item["revision"])
    return item


def _asset(session: Session, character_id: str, name: str, workspace_id: str) -> None:
    session.execute(
        text("INSERT INTO assets (id, workspace_id, name, kind, kept) VALUES (:id, :workspace_id, :name, '人物', 1)"),
        {"id": character_id, "workspace_id": workspace_id, "name": name},
    )


def _version(session: Session, character: dict[str, Any], *, images: bool = True) -> None:
    if not images:
        return
    session.execute(
        text(
            """
            INSERT INTO asset_versions (id, asset_id, version, lock_text, accepted)
            VALUES (:id, :asset_id, :version, :lock_text, 1)
            """
        ),
        {
            "id": f"{character['id']}-r{character['revision']}",
            "asset_id": character["id"],
            "version": character["revision"],
            "lock_text": character["setting"],
        },
    )


def create_character(
    session: Session,
    *,
    name: str,
    images: list[str],
    setting: str,
    voice_file_id: str,
    workspace_id: str = "ws",
) -> dict[str, Any]:
    if not name.strip():
        raise GateError("character", "人物要有名称")
    if not images:
        raise GateError("character", "人物至少要有一张参考图")
    if len(images) > IMAGE_LIMIT:
        raise GateError("limit", "参考图超过该实例上限")
    if not setting.strip():
        raise GateError("character", "人物要有设定原文")
    if not voice_file_id:
        raise GateError("character", "人物要有音色")
    character_id = "char_" + uuid.uuid4().hex[:12]
    session.execute(
        text(
            """
            INSERT INTO characters (id, workspace_id, name, images_json, setting, voice_file_id, revision)
            VALUES (:id, :workspace_id, :name, :images, :setting, :voice, 1)
            """
        ),
        {
            "id": character_id,
            "workspace_id": workspace_id,
            "name": name.strip(),
            "images": _dumps(images),
            "setting": setting,
            "voice": voice_file_id,
        },
    )
    character = _character(session, character_id)
    _asset(session, character_id, character["name"], workspace_id)
    _version(session, character)
    return character


def add_images(session: Session, character_id: str, images: list[str], revision: int) -> dict[str, Any]:
    current = _character(session, character_id)
    if int(revision) != current["revision"]:
        raise GateError("stale", "修订号对不上，先重新读取人物")
    if not images:
        raise GateError("character", "补图至少要有一张")
    merged = [*current["images"], *images]
    if len(merged) > IMAGE_LIMIT:
        raise GateError("limit", "参考图超过该实例上限")
    next_revision = current["revision"] + 1
    session.execute(
        text("UPDATE characters SET images_json = :images, revision = :revision WHERE id = :id AND revision = :expected"),
        {"images": _dumps(merged), "revision": next_revision, "id": character_id, "expected": current["revision"]},
    )
    updated = _character(session, character_id)
    if updated["images"] != merged:
        raise GateError("stale", "修订号对不上，先重新读取人物")
    _version(session, updated)
    _invalidate_slotted(session, character_id, images=True)
    return updated


def replace_setting(session: Session, character_id: str, revision: int, old: str, new: str) -> dict[str, Any]:
    current = _character(session, character_id)
    if int(revision) != current["revision"]:
        raise GateError("stale", "修订号对不上，先重新读取人物")
    if old == new:
        raise GateError("setting", "替换前后相同")
    if not old:
        raise GateError("setting", "要给出当前设定里的原文片段")
    count = current["setting"].count(old)
    if count == 0:
        raise GateError("not_found", "这段原文不在当前设定里")
    if count > 1:
        raise GateError("ambiguous", "这段原文出现多次，带上更多相邻原文再替换")
    replaced = current["setting"].replace(old, new, 1)
    next_revision = current["revision"] + 1
    session.execute(
        text("UPDATE characters SET setting = :setting, revision = :revision WHERE id = :id AND revision = :expected"),
        {"setting": replaced, "revision": next_revision, "id": character_id, "expected": current["revision"]},
    )
    updated = _character(session, character_id)
    if updated["setting"] != replaced:
        raise GateError("stale", "修订号对不上，先重新读取人物")
    _invalidate_slotted(session, character_id, images=False)
    return updated


def _invalidate_slotted(session: Session, character_id: str, *, images: bool) -> None:
    rows = session.execute(
        text("SELECT DISTINCT segment_id FROM slots WHERE asset_id = :id AND segment_id IS NOT NULL"),
        {"id": character_id},
    ).all()
    for (segment_id,) in rows:
        if images:
            session.execute(
                text("UPDATE segments SET g2 = 'pending', g4 = 'pending', prompt_accepted = 0 WHERE id = :id"),
                {"id": segment_id},
            )
        else:
            session.execute(
                text("UPDATE segments SET prompt_accepted = 0 WHERE id = :id"),
                {"id": segment_id},
            )
        session.execute(
            text("UPDATE character_refs SET stale = 1 WHERE character_id = :id AND segment_id = :segment"),
            {"id": character_id, "segment": segment_id},
        )


def cite_character(
    session: Session,
    *,
    character_id: str,
    number: int,
    occupied_image_numbers: list[int],
    image_limit: int,
    environment: dict[str, Any],
    segment_id: str | None = None,
    prototype_id: str | None = None,
) -> dict[str, Any]:
    """Pass images and voice through. The setting waits for a compressed description."""
    character = _character(session, character_id)
    if number < 1:
        raise GateError("number", "角色序号从 1 起")
    taken = set(occupied_image_numbers)
    taken.add(number)
    extras = []
    cursor = 0
    for _image in character["images"][1:]:
        while cursor in taken:
            cursor += 1
        extras.append(cursor)
        taken.add(cursor)
        cursor += 1
    image_numbers = [number, *extras]
    if any(item < 0 or item >= image_limit for item in image_numbers):
        raise GateError("limit", "参考图超过该实例上限")
    if len(set(occupied_image_numbers) | set(image_numbers)) > image_limit:
        raise GateError("limit", "参考图超过该实例上限")
    ref_id = "cref_" + uuid.uuid4().hex[:10]
    session.execute(
        text(
            """
            INSERT INTO character_refs (
              id, character_id, revision, segment_id, prototype_id, number, images_json, image_numbers_json, voice_file_id, setting, environment_json, stale
            ) VALUES (
              :id, :character_id, :revision, :segment_id, :prototype_id, :number, :images, :image_numbers, :voice, :setting, :environment, 0
            )
            """
        ),
        {
            "id": ref_id,
            "character_id": character_id,
            "revision": character["revision"],
            "segment_id": segment_id,
            "prototype_id": prototype_id,
            "number": number,
            "images": _dumps(character["images"]),
            "image_numbers": _dumps(image_numbers),
            "voice": character["voice_file_id"],
            "setting": character["setting"],
            "environment": _dumps(environment),
        },
    )
    job = enqueue(
        session,
        workspace_id=character["workspace_id"],
        job_type="specialize_character",
        payload={
            "ref_id": ref_id,
            "character_id": character_id,
            "revision": character["revision"],
            "setting": character["setting"],
            "image_numbers": image_numbers,
            "environment": environment,
        },
    )
    session.execute(text("UPDATE character_refs SET job_id = :job WHERE id = :id"), {"job": job["id"], "id": ref_id})
    body = reference_body(character["images"], character["voice_file_id"], number, image_numbers)
    return {
        "id": ref_id,
        "character_id": character_id,
        "revision": character["revision"],
        "job_id": job["id"],
        "accepted": False,
        "compressed": None,
        "body": body,
    }


def reference_body(images: list[str], voice_file_id: str, number: int, image_numbers: list[int]) -> dict[str, str]:
    body = {f"ref_image_{image_number}": image for image_number, image in zip(image_numbers, images, strict=True)}
    body[f"ref_audio_{number - 1}"] = voice_file_id
    return body


def accept_specialized(session: Session, job_id: str, compressed: str) -> dict[str, Any]:
    text_out = str(compressed or "").strip()
    if not text_out:
        raise GateError("specialize", "压缩结果不能为空")
    row = session.execute(text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id}).mappings().first()
    if row is None or row["type"] != "specialize_character" or row["status"] != "succeeded":
        raise GateError("accept", "只能接受已回传的人物压缩")
    if row["accepted_at"]:
        raise GateError("accept", "这次压缩已经接受")
    payload = _loads(row["input"], {})
    ref = session.execute(text("SELECT * FROM character_refs WHERE id = :id"), {"id": payload.get("ref_id")}).mappings().first()
    if ref is None:
        raise GateError("missing", "没有这次人物引用")
    if int(ref["revision"]) != int(payload.get("revision") or -1):
        raise GateError("stale", "人物修订已变，重新压缩")
    current = _character(session, ref["character_id"])
    if current["setting"] != ref["setting"] or current["revision"] != ref["revision"]:
        raise GateError("stale", "人物修订已变，重新压缩")
    if text_out == current["setting"]:
        raise GateError("specialize", "压缩结果不能原样抄回设定")
    session.execute(
        text("UPDATE character_refs SET compressed = :text, stale = 0 WHERE id = :id"),
        {"text": text_out, "id": ref["id"]},
    )
    session.execute(
        text("UPDATE jobs SET accepted_at = :accepted WHERE id = :id AND accepted_at IS NULL"),
        {"accepted": _now(), "id": job_id},
    )
    stored = session.execute(text("SELECT setting FROM characters WHERE id = :id"), {"id": ref["character_id"]}).first()
    if stored is None or stored[0] != current["setting"]:
        raise GateError("specialize", "压缩结果不能写回人物设定")
    return {"id": ref["id"], "compressed": text_out, "setting_unchanged": True, "accepted": True}


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def specialized_ready(session: Session, ref_id: str) -> dict[str, Any]:
    ref = session.execute(text("SELECT * FROM character_refs WHERE id = :id"), {"id": ref_id}).mappings().first()
    if ref is None:
        raise GateError("missing", "没有这次人物引用")
    current = _character(session, ref["character_id"])
    if ref["stale"] or current["revision"] != ref["revision"] or current["setting"] != ref["setting"]:
        raise GateError("stale", "人物修订已变，重新压缩")
    if not ref["compressed"]:
        raise GateError("specialize", "人物设定还没按当前环境压缩")
    images = _loads(ref["images_json"], [])
    numbers = [int(item) for item in _loads(ref["image_numbers_json"], [])]
    body = reference_body(images, ref["voice_file_id"], int(ref["number"]), numbers)
    body[f"subject_{int(ref['number'])}"] = ref["compressed"]
    if current["setting"] in body.values():
        raise GateError("specialize", "人物设定原文不能传入")
    return {"compressed": ref["compressed"], "body": body, "setting_unchanged": current["setting"] == ref["setting"]}
