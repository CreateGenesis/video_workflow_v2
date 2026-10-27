"""Acceptance sentences driven through the platform HTTP entry points."""

from __future__ import annotations

from sqlalchemy import text

from agent.app import dispatch, comic_team
from cvplatform.comic import backfill_decision
from cvplatform.db import session
from cvplatform.gates import GRID_SENTENCE, validate_prompt


def _segment(**extra):
    row = {
        "number": 1,
        "duration": 10,
        "cast": ["A", "B", "C"],
        "scene": "夜路",
        "action": "滑过",
        "dialogue": "无",
        "end_state": "停住",
    }
    row.update(extra)
    return row


def _words(count: int) -> str:
    return " ".join(["moves"] * count)


def test_command_order_and_inspiration_are_rejected(client):
    order = client.get("/api/commands").json()
    assert order["g1_before_image"] is True
    assert order["g2_before_probe"] is True
    assert order["g3_after_probe"] is True
    assert order["ratio_after_segments"] is True
    assert order["order"].index("提交分段") < order["order"].index("提交同框比例")
    blocked = client.post("/api/runs", json={"version_id": "wf_comic", "inspiration": "一句灵感"})
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "inspiration"


def test_new_episode_reuses_numbers_and_does_not_copy_segments(client):
    created = client.post("/api/runs", json={"version_id": "wf_comic", "script": "第二集剧本"}).json()
    episode = client.get(f"/api/episodes/{created['episode_id']}").json()
    assert episode["segments"] == []
    assert episode["numbers"] == [{"asset_id": "role-a", "kind": "角色", "number": 1}]
    assert created["job_id"] is None
    accepted = client.post(f"/api/episodes/{created['episode_id']}/accept-published").json()
    assert accepted["created"] is True
    assert created["copied_segments"] == 0
    assert created["reallocated"] is False
    empty = client.post("/api/runs", json={"version_id": "wf_comic", "script": "   "})
    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "script"


def test_dialogue_none_blocks_confirm_until_the_line_is_edited(client):
    episode = client.post("/api/episodes").json()["id"]
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(cast=["A"], dialogue="你好")]).json()
    segment_id = saved["items"][0]["id"]
    client.post(f"/api/episodes/{episode}/dialogue", params={"mode": "无"})
    client.post(f"/api/segments/{segment_id}/one-action", params={"checked": True})
    rejected = client.post(f"/api/segments/{segment_id}/confirm")
    assert rejected.status_code == 422
    edited = client.post(f"/api/segments/{segment_id}/edit", json={"dialogue": "无"}, params={"dialogue_mode": "无"})
    assert edited.status_code == 200
    assert edited.json()["confirmed"] is False
    confirmed = client.post(f"/api/segments/{segment_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed"] is True
    assert confirmed.json()["dialogue"] == "无"


def test_one_action_and_voiceover_slot(client):
    episode = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{episode}/dialogue", params={"mode": "有"})
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(cast=["A"], dialogue="旁白在画外")]).json()
    segment_id = saved["items"][0]["id"]
    client.post(f"/api/segments/{segment_id}/speakers", json=["旁白"])
    missing = client.post(f"/api/segments/{segment_id}/confirm")
    assert missing.json()["detail"]["code"] == "one_action"
    client.post(f"/api/segments/{segment_id}/one-action", params={"checked": True})
    voice = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "voice-narrator", "kind": "音色", "number": 0, "segment_id": segment_id, "product_id": "audio-file"},
    )
    assert voice.status_code == 200
    assert voice.json()["binding"] == {}
    assert client.post(f"/api/segments/{segment_id}/confirm").status_code == 200


def test_ratios_and_audio_binding_go_through_the_api(client):
    episode = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{episode}/segments", json=[_segment()])
    one_pair = client.post(
        f"/api/episodes/{episode}/ratios",
        json=[{"left": "A", "right": "B", "left_ratio": 7, "right_ratio": 7}],
    )
    assert one_pair.status_code == 422
    assert one_pair.json()["detail"]["code"] == "pairs"
    solo = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{solo}/segments", json=[_segment(cast=["A"])])
    assert client.post(f"/api/episodes/{solo}/ratios", json=[]).status_code == 200
    role = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "role-a", "kind": "角色", "number": 1, "segment_id": "seg-a"},
    ).json()
    assert role["binding"]["image"] == "ref_image_1"
    assert role["binding"]["audio"] == "ref_audio_0"
    assert role["binding"]["audio_tag"] == "<Audio 1>"
    switched = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "role-b", "kind": "角色", "number": 1, "segment_id": "seg-a"},
    )
    assert switched.status_code == 422


def test_unaccepted_last_frame_cannot_enter_a_slot_and_graph_reads_slots(client):
    episode = client.post("/api/episodes").json()["id"]
    blocked = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "末帧", "number": 0, "segment_id": "seg-b", "accepted": False},
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "accept"
    refused = client.post("/api/products/missing/promote", json={"kind": "末帧", "lock_text": "x"})
    assert refused.status_code == 422
    entity = client.post("/api/works/work_1/entities")
    assert entity.status_code == 422
    assert entity.json()["detail"]["code"] == "reference"


def test_probe_rejects_empty_first_frame_wrong_audio_and_missing_seed(client):
    episode = client.post("/api/episodes").json()["id"]
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(cast=["A"])]).json()
    segment_id = saved["items"][0]["id"]
    with session() as db:
        db.execute(text("UPDATE segments SET prompt = 'old', prompt_accepted = 0 WHERE id = :id"), {"id": segment_id})
    no_seed = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": ""},
    )
    assert no_seed.status_code == 422
    assert no_seed.json()["detail"]["code"] == "seed"
    with session() as db:
        db.execute(text("UPDATE segments SET prompt = NULL, prompt_accepted = 0 WHERE id = :id"), {"id": segment_id})
    empty = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9"},
    )
    assert empty.json()["detail"]["code"] == "slot"
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    )
    before_g2 = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9"},
    )
    assert before_g2.status_code == 422
    assert before_g2.json()["detail"]["code"] == "g2"
    marked = client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    assert marked.status_code == 200
    assert marked.json()["g2"] == "passed"
    opened = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9"},
    ).json()
    assert opened["spec"] == {"resolution": "480p", "mode": "高速", "duration": 2}
    assert opened["segment_duration"] == 10
    assert opened["aspect_reference"] == "480p"
    wrong_audio = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9", "audio_binding": "ref_audio_1"},
    )
    assert wrong_audio.json()["detail"]["code"] == "audio"


def test_formal_submit_uses_only_the_latest_probe_check(client):
    episode = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{episode}/dialogue", params={"mode": "无"})
    with session() as db:
        db.execute(
            text("UPDATE episodes SET aspect = '1088x1920', mode = '高质', aspect_confirmed = 1, mode_confirmed = 1 WHERE id = :id"),
            {"id": episode},
        )
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(cast=["A"], dialogue="无")]).json()
    segment_id = saved["items"][0]["id"]
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    )
    client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    first = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 5, "seed": "7"},
    ).json()
    client.post(f"/api/probe-results/{first['result_id']}/check")
    second = client.post(f"/api/segments/{segment_id}/reprobe").json()
    assert second["copied"] == {"resolution": "480p", "mode": "高速", "duration": 5.0}
    assert second["includes_seed"] is False
    assert second["includes_check"] is False
    with session() as db:
        db.execute(text("UPDATE segments SET prompt = 'accepted prompt', prompt_accepted = 1 WHERE id = :id"), {"id": segment_id})
    stale = client.post(f"/api/segments/{segment_id}/formal")
    assert stale.status_code == 422
    assert stale.json()["detail"]["code"] == "g3"
    client.post(f"/api/probe-results/{second['result_id']}/check")
    body = client.post(f"/api/segments/{segment_id}/formal").json()
    assert body["duration"] == 10
    assert body["resolution"] == "1088x1920"
    assert body["mode"] == "高质"
    assert body["seed"] == "7"
    assert body["read_probe_fields"] is False
    assert body["prompt"] == "accepted prompt"


def test_mark_failed_and_image_version_follow_the_table(client):
    episode = client.post("/api/episodes").json()["id"]
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment()]).json()
    segment_id = saved["items"][0]["id"]
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    )
    client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    client.post(f"/api/segments/{segment_id}/qc", params={"passed": True})
    with session() as db:
        db.execute(
            text("UPDATE episodes SET episode_duration = 10, aspect = '1080x1920', color_confirmed = 1, subtitles_confirmed = 1, music_confirmed = 1, loudness_confirmed = 1 WHERE id = :id"),
            {"id": episode},
        )
    ready = client.post(f"/api/episodes/{episode}/concat")
    assert ready.status_code == 200
    client.post(f"/api/segments/{segment_id}/qc", params={"passed": False})
    refused = client.post(f"/api/episodes/{episode}/concat")
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "g4"
    failed = client.post(f"/api/segments/{segment_id}/rerun", params={"change": "failed"}).json()
    assert failed["invalidate"] == ["g3", "g4"]
    assert failed["stored"]["g4"] == "pending"
    unchanged = client.get("/api/rerun", params={"change": "unchanged"}).json()
    assert unchanged["keeps_g3"] is False
    image = client.get("/api/rerun", params={"change": "image_version"}).json()
    assert "g2" in image["invalidate"]
    voice = client.get("/api/rerun", params={"change": "seed_or_voice_version"}).json()
    assert "g2" in voice["keep"]
    duration = client.get("/api/rerun", params={"change": "duration"}).json()
    assert "g2" in duration["invalidate"]
    end_state = client.get("/api/rerun", params={"change": "end_state", "has_next": True}).json()
    assert end_state["next"] == "rewrite_probe_then_render_last_frame"
    blocked = client.post("/api/segments/seg-next/next-probe", params={"last_frame_slotted": False})
    assert blocked.json()["detail"]["code"] == "last_frame"
    assert client.post("/api/segments/seg-next/next-probe", params={"last_frame_slotted": True}).json()["allowed"] is True
    last = client.get("/api/rerun", params={"change": "end_state", "has_next": False}).json()
    with session() as db:
        db.execute(text("INSERT INTO assets (id, workspace_id, name, kind, kept) VALUES ('role-can', 'ws', '红罐', '角色', 1)"))
        db.execute(text("INSERT INTO asset_versions (id, asset_id, version, lock_text, accepted) VALUES ('ver-can-1', 'role-can', 1, '红罐', 1)"))
        db.execute(text("INSERT INTO assets (id, workspace_id, name, kind, kept) VALUES ('prop-can', 'ws', '滑板', '道具', 1)"))
        db.execute(text("INSERT INTO asset_versions (id, asset_id, version, lock_text, accepted) VALUES ('ver-prop-9', 'prop-can', 9, '滑板', 1)"))
    role = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "role-can", "kind": "角色", "number": 1, "segment_id": segment_id, "product_id": "role-file"},
    )
    assert role.status_code == 200
    prop = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "prop-can", "kind": "道具", "number": 3, "segment_id": segment_id, "product_id": "prop-file"},
    )
    assert prop.status_code == 200
    refreshed = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file-pinned"},
    )
    assert refreshed.status_code == 200
    with session() as db:
        frame = db.execute(
            text("SELECT kind, asset_id, product_id, asset_version_id FROM slots WHERE segment_id = :id AND kind = '首帧'"),
            {"id": segment_id},
        ).mappings().one()
    assert frame["kind"] == "首帧"
    assert frame["asset_id"] == "frame"
    assert frame["product_id"] == "frame-file-pinned"
    client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    bumped = client.post("/api/assets/role-can/image-version", params={"segment_id": segment_id})
    assert bumped.status_code == 200
    assert bumped.json()["version"] == 2
    assert bumped.json()["g2"] == "pending"
    assert int(bumped.json()["version"]) < 9
    rechecked = client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    assert rechecked.status_code == 422
    assert rechecked.json()["detail"]["code"] == "first_frame"
    blocked_probe = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9"},
    )
    assert blocked_probe.status_code == 422
    with session() as db:
        still = db.execute(
            text("SELECT kind, asset_id, product_id FROM slots WHERE segment_id = :id AND kind = '首帧'"),
            {"id": segment_id},
        ).mappings().one()
    assert still["kind"] == "首帧"
    assert still["asset_id"] == "frame"
    assert still["product_id"] == "frame-file-pinned"
    prop_bump = client.post("/api/assets/prop-can/image-version", params={"segment_id": segment_id})
    assert prop_bump.status_code == 200
    assert prop_bump.json()["version"] == 10
    prop_g2 = client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    assert prop_g2.status_code == 422
    assert prop_g2.json()["detail"]["code"] == "first_frame"
    prop_probe = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9"},
    )
    assert prop_probe.status_code == 422
    replaced = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file-v2"},
    )
    assert replaced.status_code == 200
    passed = client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    assert passed.status_code == 200
    assert passed.json()["product_id"] == "frame-file-v2"
    opened = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9"},
    )
    assert opened.status_code == 200
    assert "next_prompt" not in last["invalidate"]


def test_lower_prop_bump_blocks_while_a_higher_character_version_exists(client):
    episode = client.post("/api/episodes").json()["id"]
    segment_id = client.post(f"/api/episodes/{episode}/segments", json=[_segment()]).json()["items"][0]["id"]
    with session() as db:
        db.execute(text("INSERT INTO assets (id, workspace_id, name, kind, kept) VALUES ('role-high', 'ws', '高版角色', '角色', 1)"))
        db.execute(text("INSERT INTO asset_versions (id, asset_id, version, lock_text, accepted) VALUES ('ver-role-9', 'role-high', 9, '高', 1)"))
        db.execute(text("INSERT INTO assets (id, workspace_id, name, kind, kept) VALUES ('prop-low', 'ws', '低版道具', '道具', 1)"))
        db.execute(text("INSERT INTO asset_versions (id, asset_id, version, lock_text, accepted) VALUES ('ver-prop-1', 'prop-low', 1, '低', 1)"))
    assert client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "role-high", "kind": "角色", "number": 1, "segment_id": segment_id, "product_id": "role-high-file"},
    ).status_code == 200
    assert client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "prop-low", "kind": "道具", "number": 4, "segment_id": segment_id, "product_id": "prop-low-file"},
    ).status_code == 200
    assert client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame-low", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    ).status_code == 200
    bumped = client.post("/api/assets/prop-low/image-version", params={"segment_id": segment_id})
    assert bumped.status_code == 200
    assert bumped.json()["version"] == 2
    assert bumped.json()["version"] < 9
    rechecked = client.post(f"/api/segments/{segment_id}/g2", params={"passed": True})
    assert rechecked.status_code == 422
    assert rechecked.json()["detail"]["code"] == "first_frame"
    probe = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "3"},
    )
    assert probe.status_code == 422
    assert probe.json()["detail"]["code"] == "first_frame"
    with session() as db:
        still = db.execute(
            text("SELECT kind, product_id FROM slots WHERE segment_id = :id AND kind = '首帧'"),
            {"id": segment_id},
        ).mappings().one()
    assert still["kind"] == "首帧"
    assert still["product_id"] == "frame-file"
    replaced = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame-low", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file-new"},
    )
    assert replaced.status_code == 200
    assert client.post(f"/api/segments/{segment_id}/g2", params={"passed": True}).status_code == 200
    opened = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "3"},
    )
    assert opened.status_code == 200


def test_prompt_validation_sentences(client):
    slots = [
        {"kind": "角色", "number": 1, "empty": False, "lock_text": "红罐"},
        {"kind": "角色", "number": 2, "empty": True, "lock_text": ""},
        {"kind": "场景", "number": 3, "empty": False, "lock_text": "夜路"},
    ]
    sections = {
        "summary": "A night street with <Picture 1> from ref_image_0.",
        "detailed_description": _words(360) + " 0.000 9.000 <d>你好</d>",
        "overall_soundscape": "wind",
    }
    full = "<Subject 1>: 红罐\n<Picture 4> <Subject 3>: 夜路\n" + sections["summary"] + sections["detailed_description"] + " " + GRID_SENTENCE
    ok = client.post("/api/prompts/validate", json={"full_text": full, "slots": slots, "sections": sections, "duration": 10}).json()
    assert ok["ok"] is True
    assert "<Subject 2>" not in "\n".join(ok["lines"])
    picture = full.replace("<Picture 1>", "<Picture 2>")
    bad_picture = client.post("/api/prompts/validate", json={"full_text": picture, "slots": slots, "sections": {**sections, "summary": "ref_image_0 as <Picture 2>"}, "duration": 10}).json()
    assert bad_picture["ok"] is False
    missing_grid = client.post(
        "/api/prompts/validate",
        json={"full_text": full.replace(GRID_SENTENCE, ""), "slots": slots, "sections": sections, "duration": 10},
    ).json()
    assert "grid_sentence" in missing_grid["errors"]
    short = dict(sections)
    short["detailed_description"] = _words(200)
    short_result = client.post("/api/prompts/validate", json={"full_text": full, "slots": slots, "sections": short, "duration": 10}).json()
    assert "word_count" in short_result["errors"]
    doubled = dict(sections)
    doubled["summary"] = sections["summary"] + " subject_definitions"
    doubled_result = client.post("/api/prompts/validate", json={"full_text": full, "slots": slots, "sections": doubled, "duration": 10}).json()
    assert "second_lock_block" in doubled_result["errors"]
    errors = validate_prompt(full, slots, sections, 10)
    assert errors == []


def test_adsorbed_duration_does_not_count_as_episode_duration(client):
    episode_id = client.post("/api/episodes").json()["id"]
    saved = client.post(
        f"/api/episodes/{episode_id}/segments",
        json=[_segment(duration=10.13), _segment(number=2, duration=4.87)],
    ).json()
    with session() as db:
        db.execute(
            text(
                """
                UPDATE episodes
                SET episode_duration = 20, aspect = '1080x1920',
                    color_confirmed = 1, subtitles_confirmed = 1, music_confirmed = 1, loudness_confirmed = 1
                WHERE id = :id
                """
            ),
            {"id": episode_id},
        )
        db.execute(text("UPDATE segments SET g4 = 'passed' WHERE episode_id = :id"), {"id": episode_id})
    caller_g4 = client.post(
        "/api/concat/ready",
        json={
            "episode_id": episode_id,
            "segments": [{"number": 1, "duration": 10, "g4": "passed"}, {"number": 2, "duration": 10, "g4": "passed"}],
            "episode": {"episode_duration": 20, "g4": "passed"},
        },
    )
    assert caller_g4.status_code == 422
    assert caller_g4.json()["detail"]["code"] == "g4"
    stored = client.post("/api/concat/ready", json={"episode_id": episode_id})
    assert stored.status_code == 422
    assert stored.json()["detail"]["code"] == "episode_duration"
    with session() as db:
        db.execute(text("UPDATE segments SET duration = 10 WHERE episode_id = :id"), {"id": episode_id})
        db.execute(text("UPDATE segments SET g4 = 'pending' WHERE id = :id"), {"id": saved["items"][0]["id"]})
    forged = client.post(
        "/api/concat/ready",
        json={"episode_id": episode_id, "segments": [{"number": 1, "duration": 10, "g4": "passed"}]},
    )
    assert forged.status_code == 422
    assert forged.json()["detail"]["code"] == "g4"
    with session() as db:
        db.execute(text("UPDATE segments SET g4 = 'passed' WHERE episode_id = :id"), {"id": episode_id})
    matched = client.post("/api/concat/ready", json={"episode_id": episode_id})
    assert matched.status_code == 200
    assert matched.json()["scale"] == "1080x1920"
    assert client.post(f"/api/episodes/{episode_id}/concat").status_code == 200


def test_concat_price_g1_and_backfill(client):
    missing_price = client.post("/api/estimate", params={"kind": "video", "quantity": 10})
    assert missing_price.status_code == 422
    concat = client.post("/api/estimate", params={"kind": "concat", "quantity": 1}).json()
    assert concat["amount"] == 0
    blocked = client.post("/api/first-frame/allowed", json={"g1": "pending", "speakers": ["A"], "voices": ["A"]})
    assert blocked.json()["detail"]["code"] == "g1"
    no_voice = client.post("/api/first-frame/allowed", json={"g1": "passed", "speakers": ["旁白"], "voices": []})
    assert no_voice.json()["detail"]["code"] == "voice"
    assert client.post("/api/first-frame/allowed", json={"g1": "passed", "speakers": ["旁白"], "voices": ["旁白"]}).json()["allowed"] is True
    assert client.get("/api/segments/seg-1/g4", params={"number": 1}).json()["checks_seam"] is False
    assert client.get("/api/segments/seg-2/g4", params={"number": 2}).json()["checks_seam"] is True
    early = client.post("/api/backfill/export", params={"process_stopped": False})
    assert early.json()["detail"]["code"] == "backfill"
    assert client.post("/api/backfill/export", params={"process_stopped": True}).json()["allowed"] is True
    with session() as db:
        db.execute(text("INSERT INTO assets (id, workspace_id, name, kind, kept) VALUES ('kick-red', 'ws', 'kick-red', '主体', 1)"))
        db.execute(text("INSERT INTO assets (id, workspace_id, name, kind, kept) VALUES ('ref-unused', 'ws', 'unused', 'Reference', 1)"))
    stopped = client.post(
        "/api/backfill/run",
        params={"process_stopped": False},
        json={"work_id": "work_1adb1aed6c084c3e", "entity_ids": ["kick-red", "ref-unused"]},
    )
    assert stopped.status_code == 422
    ran = client.post(
        "/api/backfill/run",
        params={"process_stopped": True},
        json={"work_id": "work_1adb1aed6c084c3e", "entity_ids": ["kick-red", "ref-unused"]},
    ).json()
    assert "kick-red" in ran["kept"]
    assert "ref-unused" in ran["removed"]
    assert any(item["name"].startswith("kick-") for item in ran["library"])
    assert backfill_decision(task_input=False, clip_chain=False, asset_link=False, promoted=True) == "keep"
    assert backfill_decision(task_input=False, clip_chain=False, asset_link=False, promoted=False) == "soft_delete"


def test_probe_errors_and_lead_routing(client):
    from cvplatform.probes import judge_benchmark, probe_h3, probe_image, probe_text

    def boom(method, url, payload, token):
        raise RuntimeError("upstream refused raw token")

    failed = probe_text("http://example", "raw", transport=boom)
    assert failed["sent"]["messages"][0]["content"] == "hi"
    assert "upstream refused" in failed["error"]

    def image_url(method, url, payload, token):
        return {"data": [{"url": "http://unreachable"}]}

    assert probe_image("http://example", "raw", transport=image_url)["ok"] is False
    try:
        probe_h3("http://example", "Bearer secret", "minimax_h3_803", transport=boom)
    except Exception as exc:  # noqa: BLE001
        assert "裸 token" in str(exc)
    team = comic_team()
    assert dispatch(team, "write_prompt") == "prompt-only"
    assert dispatch(team, "segment_script") == "segment-only"
    assert judge_benchmark("write_prompt", {"summary": "a", "detailed_description": "b", "overall_soundscape": "c"}, visual=True) == "passed"
    assert judge_benchmark("write_prompt", {"summary": "subject_definitions"}, visual=True) == "failed"
