"""Agent worker HTTP surface. Model calls happen only after a successful claim."""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI

app = FastAPI(title="cvgen-agent", version="3.0.0")
PROCESS = "agent"


def platform_base() -> str:
    return os.environ.get("CVGEN_PLATFORM_URL", "http://127.0.0.1:8093")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"process": PROCESS, "service": "agent-worker"}


@app.post("/api/claim-once")
def claim_once(owner: str = "agent-1") -> dict[str, Any]:
    """Claim through the platform. No row means the model is not called."""
    response = httpx.post(f"{platform_base()}/api/jobs/claim", params={"owner": owner}, timeout=10)
    response.raise_for_status()
    body = response.json()
    body["model_called"] = bool(body.get("claimed"))
    body["process"] = PROCESS
    return body


@app.post("/api/complete")
def complete(job_id: str, owner: str, output: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.post(
        f"{platform_base()}/api/jobs/{job_id}/complete",
        json={"owner": owner, "output": output or {}, "error": None},
        timeout=10,
    )
    return {"status_code": response.status_code, "body": response.json(), "process": PROCESS}


def route(job_type: str) -> str:
    """The lead does not call the model. Members do not cross types."""
    members = {
        "segment_script": "segment-only",
        "write_prompt": "prompt-only",
        "extract_reference": "lock-draft-only",
    }
    if job_type not in members:
        raise ValueError("未知任务类型")
    return members[job_type]


def main() -> None:
    import uvicorn

    port = int(os.environ.get("CVGEN_AGENT_PORT", "8094"))
    uvicorn.run("agent.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
