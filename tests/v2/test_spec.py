"""Workflow spec checks that block publishing."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from server import db
from server.samples import seed_samples
from server.workflows.spec import analyze, same_items, semantic_check, structure_errors

EXAMPLES = Path(__file__).parents[2] / "docs" / "design" / "examples"
PRODUCT = json.loads((EXAMPLES / "product-ad.workflow.json").read_text(encoding="utf-8"))
ZERO = json.loads((EXAMPLES / "zero-snow.workflow.json").read_text(encoding="utf-8"))


def _node(spec: dict, node_id: str) -> dict:
    return next(node for node in spec["nodes"] if node["id"] == node_id)


def test_structure_messages_point_at_the_node():
    spec = copy.deepcopy(PRODUCT)
    _node(spec, "keyframes")["role"] = "背景"
    errors = structure_errors(spec)
    assert any("keyframes" in error and "role" in error for error in errors)


def test_analysis_order_items_and_cycles():
    analysis = analyze(PRODUCT)
    assert analysis.errors == []
    assert analysis.order.index("script") < analysis.order.index("keyframes") < analysis.order.index("review")
    assert analysis.deps["clips"] == {"review", "script"}
    assert same_items(analysis, "clips", "keyframes") and same_items(analysis, "qc", "clips")
    assert analysis.roots["qc"] == ("node", "script", "shots")
    looped = copy.deepcopy(PRODUCT)
    _node(looped, "script")["after"] = ["final"]
    assert any("循环" in error for error in analyze(looped).errors)
    dangling = copy.deepcopy(PRODUCT)
    _node(dangling, "final")["after"] = ["nope"]
    assert any("nope" in error for error in analyze(dangling).errors)


def test_semantic_checks(fresh, mock_providers):
    seed_samples(fresh["workspace_id"])
    with db.tx() as conn:
        assert semantic_check(conn, fresh["workspace_id"], PRODUCT)["errors"] == []
        assert semantic_check(conn, fresh["workspace_id"], ZERO)["errors"] == []

        bad = copy.deepcopy(ZERO)
        bad["assets"]["style"] = "asset:style-snow-film@9"
        _node(bad, "adapt")["prompt"]["user"] += "{{inputs.missing}}{{assets.nothing}}"
        _node(bad, "clip")["retry"] = {"max_attempts": 3}
        errors = semantic_check(conn, fresh["workspace_id"], bad)["errors"]
        assert any("style-snow-film@9" in error for error in errors)
        assert any("inputs.missing" in error for error in errors)
        assert any("assets.nothing" in error for error in errors)
        assert any("按次计费" in error for error in errors)

        from server.auth import SYSTEM
        from server.providers import instances

        instances.save(conn, SYSTEM, "video.comfy-gpu1", {"protocol": "comfyui", "base_url": "http://gpu1:8188"})
        no_template = copy.deepcopy(PRODUCT)
        _node(no_template, "clips").pop("template")
        assert any("template" in error for error in semantic_check(conn, fresh["workspace_id"], no_template)["errors"])

        wrong_link = copy.deepcopy(ZERO)
        _node(wrong_link, "adapt")["materialize"]["shot"]["links"].append({"name": "styled_as", "to": "{{assets.place}}"})
        errors = semantic_check(conn, fresh["workspace_id"], wrong_link)["errors"]
        assert any("styled_as" in error and "Place" in error for error in errors)

        no_gate = semantic_check(conn, fresh["workspace_id"], ZERO)["warnings"]
        assert any("没有闸门" in warning for warning in no_gate)
