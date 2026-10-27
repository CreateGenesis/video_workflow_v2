"""Comic gates through the platform functions the API calls."""

from __future__ import annotations

import pytest

from cvplatform.gates import (
    GateError,
    adsorb,
    character_slots,
    check_ratios,
    concat_ready,
    copy_probe_fields,
    formal_submit_body,
    promote_allowed,
    rerun,
    save_segment_row,
    subject_lines,
    validate_prompt,
)


def _row(**extra):
    base = {
        "number": 1,
        "duration": 10,
        "cast": ["A"],
        "scene": "夜路",
        "action": "滑过",
        "dialogue": "无",
        "end_state": "停住",
    }
    base.update(extra)
    return base


def test_save_keeps_seven_columns_and_forces_unconfirmed():
    saved = save_segment_row(_row(confirmed=True, speakers=["A"]))
    assert saved["confirmed"] is False
    assert "speakers" not in saved
    assert saved["frames"] == 243


def test_dialogue_none_with_a_line_is_rejected():
    with pytest.raises(GateError) as caught:
        save_segment_row(_row(dialogue="你好", dialogue_mode="无"))
    assert caught.value.code == "dialogue_mismatch"


def test_three_characters_need_every_pair():
    segments = [{"cast": ["A", "B", "C"]}]
    with pytest.raises(GateError):
        check_ratios(segments, [{"left": "A", "right": "B", "left_ratio": 7, "right_ratio": 7}])
    check_ratios(
        segments,
        [
            {"left": "A", "right": "B", "left_ratio": 7.0, "right_ratio": 7.2},
            {"left": "A", "right": "C", "left_ratio": 6.0, "right_ratio": 6.1},
            {"left": "B", "right": "C", "left_ratio": 5.0, "right_ratio": 5.1},
        ],
    )


def test_ratios_have_no_source_before_the_segment_table():
    with pytest.raises(GateError) as caught:
        check_ratios([], [])
    assert caught.value.code == "no_segments"


def test_character_a_audio_is_ref_audio_0():
    binding = character_slots(1)
    assert binding["image"] == "ref_image_1"
    assert binding["audio"] == "ref_audio_0"
    assert binding["audio_tag"] == "<Audio 1>"
    assert binding["picture_tag"] == "<Picture 2>"


def test_empty_slot_does_not_emit_subject_2():
    slots = [
        {"kind": "角色", "number": 1, "empty": False, "lock_text": "红罐"},
        {"kind": "角色", "number": 2, "empty": True, "lock_text": ""},
        {"kind": "场景", "number": 3, "empty": False, "lock_text": "夜路九宫格"},
    ]
    lines = subject_lines(slots)
    assert "<Subject 2>" not in "\n".join(lines)
    assert "<Subject 3>: 夜路九宫格" in lines
    assert "<Subject 1>: 红罐" in lines


def test_ten_seconds_adsorbs_to_243_frames():
    found = adsorb(10)
    assert found["k"] == 14
    assert found["frames"] == 243
    assert found["actual_seconds"] == pytest.approx(243 / 24)


def test_formal_submit_ignores_probe_fields():
    segment = {
        "prompt": "accepted",
        "prompt_accepted": True,
        "seed": "7",
        "duration": 10,
        "aspect": "1088x1920",
        "mode": "高质",
        "latest_probe": {"g3": "passed", "resolution": "480p", "mode": "高速", "duration": 5},
    }
    slots = [{"kind": "首帧", "number": 0, "empty": False, "file": "frame"}]
    body = formal_submit_body(segment, slots)
    assert body["duration"] == 10
    assert body["resolution"] == "1088x1920"
    assert body["mode"] == "高质"
    assert body["seed"] == "7"
    assert "480p" not in body.values()


def test_reprobe_copies_only_three_fields():
    copied = copy_probe_fields({"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9", "g3": "passed"})
    assert copied == {"resolution": "480p", "mode": "高速", "duration": 2}


def test_unchanged_row_does_not_keep_g3():
    plan = rerun("unchanged")
    assert "g3" not in plan["invalidate"]
    assert plan["keeps_g3"] is False
    assert plan["next"] == "copy_probe_fields_new_result"


def test_image_version_drops_g2_and_voice_version_keeps_it():
    assert "g2" in rerun("image_version")["invalidate"]
    assert "g2" in rerun("seed_or_voice_version")["keep"]


def test_end_state_rewrites_this_segment_before_the_next_probe():
    plan = rerun("end_state", has_next=True)
    assert plan["next"] == "rewrite_probe_then_render_last_frame"
    assert "next_g2" in plan["invalidate"]
    last = rerun("end_state", has_next=False)
    assert "next_g2" not in last["invalidate"]


def test_first_frame_and_last_frame_cannot_be_promoted():
    assert promote_allowed("三视图")
    assert promote_allowed("音色")
    assert not promote_allowed("首帧")
    assert not promote_allowed("末帧")
    assert not promote_allowed("同框比例图")


def test_concat_rejects_adsorbed_duration_and_scales_1088_to_1080():
    segments = [{"duration": 10, "g4": "passed"}, {"duration": 10, "g4": "passed"}]
    episode = {
        "episode_duration": 20,
        "color_confirmed": True,
        "subtitles_confirmed": True,
        "music_confirmed": True,
        "loudness_confirmed": True,
        "color_grade": "无",
        "aspect": "1080x1920",
        "segment_size": (1088, 1920),
    }
    assert concat_ready(segments, episode)["scale"] == "1080x1920"
    bad = dict(episode)
    bad["episode_duration"] = 20.26
    with pytest.raises(GateError):
        concat_ready(segments, bad)


def _sections(words: int = 360) -> dict[str, str]:
    detailed = " ".join(["moves"] * words) + " 0.000 1.000 <d>你好</d>"
    return {
        "summary": "A night street.",
        "detailed_description": detailed,
        "overall_soundscape": "wind",
    }


def test_chinese_inside_d_passes_and_wrong_subject_fails():
    slots = [
        {"kind": "角色", "number": 1, "empty": False, "lock_text": "红罐"},
        {"kind": "场景", "number": 3, "empty": False, "lock_text": "夜路"},
    ]
    sections = _sections()
    full = "<Subject 1>: 红罐\n<Subject 3>: 夜路\n" + sections["summary"] + sections["detailed_description"]
    full += " " + "The grid lines and labels of the reference board do not appear in the picture."
    errors = validate_prompt(full, slots, sections, 10)
    assert "word_count" not in errors
    wrong = full.replace("<Subject 3>", "<Subject 2>")
    assert "lock_mismatch" in validate_prompt(wrong, slots, sections, 10) or "empty_subject" in validate_prompt(wrong, slots, sections, 10)
