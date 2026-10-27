"""Agent worker. Agno dispatches a claimed job to one member. The platform does not import this."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.team.mode import TeamMode
from agno.team.team import Team
from agno.tools.mcp import MCPTools
from fastapi import FastAPI

app = FastAPI(title="cvgen-agent", version="3.0.0")
PROCESS = "agent"

MEMBERS = {
    "segment_script": ("segment-only", "只回分段表的七列"),
    "write_prompt": ("prompt-only", "只填三段提示词"),
    "extract_reference": ("lock-draft-only", "只回可复制的锁段草稿"),
    "specialize_character": ("specialize-only", "只回当前环境下压缩后的人物特征"),
}


def platform_base() -> str:
    return os.environ.get("CVGEN_PLATFORM_URL", "http://127.0.0.1:8093")


class LeadModel(Model):
    """The lead does not call a provider. It only names the member for this job type."""

    id: str = "lead"
    name: str = "lead"
    provider: str = "cvgen"

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        messages = kwargs.get("messages") or (args[0] if args else [])
        job_type = ""
        for message in reversed(list(messages)):
            content = getattr(message, "content", None)
            if isinstance(content, str) and content in MEMBERS:
                job_type = content
                break
        if not job_type:
            return ModelResponse(content="未知任务类型")
        member_id = MEMBERS[job_type][0]
        return ModelResponse(
            tool_calls=[
                {
                    "id": "lead-1",
                    "type": "function",
                    "function": {
                        "name": "delegate_task_to_member",
                        "arguments": json.dumps({"member_id": member_id, "task": job_type}),
                    },
                }
            ]
        )

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._parse_provider_response(response)


class MemberModel(Model):
    """A member returns its own id. The lead must not rewrite that result."""

    id: str = "member"
    name: str = "member"
    provider: str = "cvgen"

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse(content=self.id)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any):
        yield self.invoke(*args, **kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._parse_provider_response(response)


def comic_team(mcp_tools: MCPTools | None = None) -> Team:
    members = []
    for job_type, (member_id, role) in MEMBERS.items():
        tools = [mcp_tools] if job_type == "segment_script" and mcp_tools is not None else None
        model = MemberModel(id=member_id, name=member_id)
        members.append(Agent(id=member_id, name=member_id, role=role, model=model, tools=tools))
    return Team(
        id="comic-text",
        name="漫剧文本",
        mode=TeamMode.route,
        members=members,
        model=LeadModel(id="lead"),
        determine_input_for_members=False,
        telemetry=False,
    )


def verified_mcp(card: dict[str, Any] | None) -> MCPTools | None:
    """Only a verified external card becomes MCPTools. Prompt and lock members never get one."""
    if not card or card.get("status") != "可用" or not card.get("address"):
        return None
    address = str(card["address"])
    if address.startswith("stdio:"):
        return MCPTools(command=address.removeprefix("stdio:"), transport="stdio")
    return MCPTools(url=address, transport="streamable-http")


def dispatch(team: Team, job_type: str) -> str:
    """Run the Agno team. The member id comes back unchanged."""
    result = team.run(job_type)
    content = str(result.content or "")
    if content not in {member_id for member_id, _role in MEMBERS.values()}:
        raise ValueError(content or "领队没有把任务交给成员")
    return content


def attach_mcp(job: dict[str, Any]) -> MCPTools | None:
    if job.get("type") != "segment_script" or not (job.get("input") or {}).get("needs_external"):
        return None
    tool = verified_mcp((job.get("input") or {}).get("mcp"))
    if tool is None:
        raise ValueError("未验证的 MCP 不参与依赖外站材料的分段")
    return tool


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"process": PROCESS, "service": "agent-worker"}


@app.post("/api/claim-once")
def claim_once(owner: str = "agent-1") -> dict[str, Any]:
    """Claim through the platform. No row means the model is not called."""
    response = httpx.post(f"{platform_base()}/api/jobs/claim", params={"owner": owner}, timeout=10)
    response.raise_for_status()
    body = response.json()
    job = body.get("job") or {}
    if body.get("claimed"):
        tool = attach_mcp(job)
        body["member"] = dispatch(comic_team(tool), str(job.get("type") or ""))
        body["model_called"] = True
        body["mcp"] = bool(tool)
    else:
        body["member"] = None
        body["model_called"] = False
        body["mcp"] = False
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


def main() -> None:
    import uvicorn

    port = int(os.environ.get("CVGEN_AGENT_PORT", "8094"))
    uvicorn.run("agent.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
