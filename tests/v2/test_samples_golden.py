"""The snowfield workflow, compiled from its fixture, must match the v1 composer word for word."""

from __future__ import annotations

import json
from pathlib import Path

from server import db
from server.samples import seed_samples
from server.workflows.dryrun import compile_run
from server.workflows.runner import get_version

GOLDEN = json.loads((Path(__file__).parents[1] / "golden" / "zero_shot_768p.json").read_text(encoding="utf-8"))


def test_examples_pass_schema_and_docs_copy_is_identical():
    from server.workflows.spec import SCHEMA_PATH, structure_errors

    docs = Path(__file__).parents[2] / "docs" / "design"
    assert (docs / "workflow.v1.schema.json").read_text() == SCHEMA_PATH.read_text()
    for name in ("zero-snow", "product-ad"):
        spec = json.loads((docs / "examples" / f"{name}.workflow.json").read_text(encoding="utf-8"))
        assert structure_errors(spec) == []


def test_zero_compile_matches_v1_prompt(fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    zero = seeded["workflows"]["zero-snow"]
    assert zero["errors"] == []
    with db.tx() as conn:
        version = get_version(conn, zero["workflow_id"], 1, published_only=False)
        result = compile_run(conn, fresh["workspace_id"], version["spec"], {"passage": "原文"}, version["fixtures"])
    assert result["problems"] == []
    assert len(result["prompts"]) == 1
    prompt = result["prompts"][0]
    assert prompt["prompt"] == GOLDEN["prompt"]
    assert prompt["warnings"] == GOLDEN["warnings"]
    assert prompt["references"] == GOLDEN["reference_titles"]
    assert result["estimate_yuan"] > 0


def test_seed_is_idempotent(fresh, mock_providers):
    first = seed_samples(fresh["workspace_id"])
    second = seed_samples(fresh["workspace_id"])
    assert second["workflows"]["zero-snow"]["skipped"] is True
    assert first["workflows"]["product-ad"]["workflow_id"] == second["workflows"]["product-ad"]["workflow_id"]
