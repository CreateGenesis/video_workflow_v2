"""Characters are uploaded complete. The platform stores, patches, and cites them."""

from __future__ import annotations

from sqlalchemy import text

from cvplatform.db import session


def _character(client, images=None, setting="红罐短发，声线清亮。"):
    created = client.post(
        "/api/characters",
        json={
            "name": "红罐",
            "images": images or ["img-front"],
            "setting": setting,
            "voice_file_id": "voice-1",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def test_create_requires_image_setting_and_voice(client):
    missing = client.post("/api/characters", json={"name": "红罐", "images": [], "setting": "设定", "voice_file_id": "voice-1"})
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "character"
    no_voice = client.post("/api/characters", json={"name": "红罐", "images": ["img"], "setting": "设定", "voice_file_id": ""})
    assert no_voice.status_code == 422
    created = _character(client, ["img-front", "img-side"])
    assert created["revision"] == 1
    assert created["images"] == ["img-front", "img-side"]
    assert created["voice_file_id"] == "voice-1"
    promoted = client.post("/api/products/prod-1/promote", json={"kind": "人物", "lock_text": "不该提升"})
    assert promoted.status_code == 422


def test_setting_replace_is_exact_and_stale_revisions_fail(client):
    created = _character(client, setting="红罐短发。夜路里声线清亮。红罐短发。")
    stale = client.post(
        f"/api/characters/{created['id']}/setting",
        json={"revision": 0, "old": "夜路里声线清亮。", "new": "雨里声线压低。"},
    )
    assert stale.status_code == 422
    assert stale.json()["detail"]["code"] == "stale"
    ambiguous = client.post(
        f"/api/characters/{created['id']}/setting",
        json={"revision": 1, "old": "红罐短发。", "new": "红罐长发。"},
    )
    assert ambiguous.status_code == 422
    assert ambiguous.json()["detail"]["code"] == "ambiguous"
    missing = client.post(
        f"/api/characters/{created['id']}/setting",
        json={"revision": 1, "old": "不存在", "new": "别的"},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "not_found"
    same = client.post(
        f"/api/characters/{created['id']}/setting",
        json={"revision": 1, "old": "夜路里声线清亮。", "new": "夜路里声线清亮。"},
    )
    assert same.status_code == 422
    replaced = client.post(
        f"/api/characters/{created['id']}/setting",
        json={"revision": 1, "old": "夜路里声线清亮。", "new": "雨里声线压低。"},
    )
    assert replaced.status_code == 200
    body = replaced.json()
    assert body["revision"] == 2
    assert body["setting"] == "红罐短发。雨里声线压低。红罐短发。"
    assert body["images"] == ["img-front"]
    overwrite = client.put(f"/api/characters/{created['id']}")
    assert overwrite.status_code == 405


def test_image_add_appends_and_requires_the_read_revision(client):
    created = _character(client)
    stale = client.post(
        f"/api/characters/{created['id']}/images",
        json={"revision": 9, "images": ["img-extra"]},
    )
    assert stale.status_code == 422
    assert stale.json()["detail"]["code"] == "stale"
    added = client.post(
        f"/api/characters/{created['id']}/images",
        json={"revision": created["revision"], "images": ["img-extra"]},
    )
    assert added.status_code == 200
    assert added.json()["images"] == ["img-front", "img-extra"]
    assert added.json()["revision"] == 2
    current = client.get(f"/api/characters/{created['id']}").json()
    assert current["images"][0] == "img-front"


def test_cite_passes_files_and_waits_for_compressed_setting(client):
    created = _character(client, ["img-front", "img-side", "img-back"])
    episode = client.post("/api/episodes").json()["id"]
    segment_id = client.post(
        f"/api/episodes/{episode}/segments",
        json=[{"number": 1, "duration": 6, "cast": ["红罐"], "scene": "夜路", "action": "滑过", "dialogue": "无", "end_state": "停住"}],
    ).json()["items"][0]["id"]
    cited = client.post(
        f"/api/characters/{created['id']}/cite",
        json={
            "number": 1,
            "occupied_image_numbers": [0],
            "image_limit": 9,
            "environment": {"scene": "夜路", "action": "滑过", "dialogue": "无", "end_state": "停住"},
            "segment_id": segment_id,
        },
    )
    assert cited.status_code == 200, cited.text
    body = cited.json()
    assert body["accepted"] is False
    assert body["body"]["ref_image_1"] == "img-front"
    assert body["body"]["ref_image_2"] == "img-side"
    assert body["body"]["ref_image_3"] == "img-back"
    assert body["body"]["ref_audio_0"] == "voice-1"
    assert created["setting"] not in body["body"].values()
    blocked = client.post(f"/api/characters/refs/{body['id']}/ready")
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "specialize"
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    )
    client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    probe = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "7"},
    )
    assert probe.status_code == 422
    assert probe.json()["detail"]["code"] == "specialize"
    completed = client.post(
        f"/api/jobs/{body['job_id']}/complete",
        json={"owner": "nobody", "output": {"compressed": "夜路里的短发红罐"}, "error": None},
    )
    assert completed.status_code == 422
    with session() as db:
        db.execute(
            text("UPDATE jobs SET status = 'leased', lease_owner = 'agent-1', lease_expires_at = '2999-01-01T00:00:00+00:00' WHERE id = :id"),
            {"id": body["job_id"]},
        )
    owned = client.post(
        f"/api/jobs/{body['job_id']}/complete",
        json={"owner": "agent-1", "output": {"compressed": "夜路里的短发红罐"}, "error": None},
    )
    assert owned.status_code == 200
    copied = client.post(f"/api/jobs/{body['job_id']}/accept-character", json={"compressed": created["setting"]})
    assert copied.status_code == 422
    accepted = client.post(f"/api/jobs/{body['job_id']}/accept-character", json={"compressed": "夜路里的短发红罐"})
    assert accepted.status_code == 200
    assert accepted.json()["setting_unchanged"] is True
    ready = client.post(f"/api/characters/refs/{body['id']}/ready")
    assert ready.status_code == 200
    assert ready.json()["body"]["ref_image_1"] == "img-front"
    assert ready.json()["body"]["ref_audio_0"] == "voice-1"
    assert ready.json()["body"]["subject_1"] == "夜路里的短发红罐"
    assert ready.json()["setting_unchanged"] is True
    opened = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "7"},
    )
    assert opened.status_code == 200


def test_added_image_blocks_g2_until_a_new_first_frame(client):
    created = _character(client)
    episode = client.post("/api/episodes").json()["id"]
    segment_id = client.post(
        f"/api/episodes/{episode}/segments",
        json=[{"number": 1, "duration": 6, "cast": ["红罐"], "scene": "夜路", "action": "滑过", "dialogue": "无", "end_state": "停住"}],
    ).json()["items"][0]["id"]
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    )
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": created["id"], "kind": "人物", "number": 1, "segment_id": segment_id, "product_id": "img-front"},
    )
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file-pinned"},
    )
    assert client.post(f"/api/segments/{segment_id}/g2", params={"passed": True}).status_code == 200
    added = client.post(
        f"/api/characters/{created['id']}/images",
        json={"revision": created["revision"], "images": ["img-extra"]},
    )
    assert added.status_code == 200
    rechecked = client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    assert rechecked.status_code == 422
    assert rechecked.json()["detail"]["code"] == "first_frame"
    replaced = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file-new"},
    )
    assert replaced.status_code == 200
    assert client.post(f"/api/segments/{segment_id}/g2", params={"passed": True}).status_code == 200


def test_setting_edit_keeps_g2_and_drops_the_old_compression(client):
    created = _character(client, setting="红罐短发，声线清亮。")
    episode = client.post("/api/episodes").json()["id"]
    segment_id = client.post(
        f"/api/episodes/{episode}/segments",
        json=[{"number": 1, "duration": 6, "cast": ["红罐"], "scene": "夜路", "action": "滑过", "dialogue": "无", "end_state": "停住"}],
    ).json()["items"][0]["id"]
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    )
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": created["id"], "kind": "人物", "number": 1, "segment_id": segment_id, "product_id": "img-front"},
    )
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file-pinned"},
    )
    assert client.post(f"/api/segments/{segment_id}/g2", params={"passed": True}).status_code == 200
    cited = client.post(
        f"/api/characters/{created['id']}/cite",
        json={
            "number": 1,
            "occupied_image_numbers": [0],
            "image_limit": 9,
            "environment": {"scene": "夜路", "action": "滑过"},
            "segment_id": segment_id,
            "prototype_id": "proto-1",
        },
    ).json()
    with session() as db:
        db.execute(
            text("UPDATE jobs SET status = 'succeeded', lease_owner = 'agent-1' WHERE id = :id"),
            {"id": cited["job_id"]},
        )
    assert client.post(f"/api/jobs/{cited['job_id']}/accept-character", json={"compressed": "夜路短发"}).status_code == 200
    edited = client.post(
        f"/api/characters/{created['id']}/setting",
        json={"revision": created["revision"], "old": "声线清亮。", "new": "声线压低。"},
    )
    assert edited.status_code == 200
    with session() as db:
        g2 = db.execute(text("SELECT g2 FROM segments WHERE id = :id"), {"id": segment_id}).scalar()
    assert g2 == "passed"
    ready = client.post(f"/api/characters/refs/{cited['id']}/ready")
    assert ready.status_code == 422
    assert ready.json()["detail"]["code"] == "stale"
