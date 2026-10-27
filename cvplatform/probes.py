"""Provider probes and the three benchmark contracts. No paid submit."""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.orm import Session

from cvplatform.gates import GRID_SENTENCE, GateError, h3_auth_header


def probe_text(base_url: str, token: str, *, transport=None) -> dict[str, Any]:
    transport = transport or _http
    sent = {"messages": [{"role": "user", "content": "hi"}]}
    try:
        body = transport("POST", base_url.rstrip("/") + "/v1/chat/completions", sent, token)
    except Exception as exc:  # noqa: BLE001 — probe must return the upstream error text
        return {"ok": False, "reply": "", "sent": sent, "error": str(exc)}
    reply = ""
    if isinstance(body, dict):
        choices = body.get("choices") or []
        if choices:
            reply = ((choices[0].get("message") or {}).get("content")) or ""
        reply = reply or body.get("reply") or ""
    return {"ok": bool(reply), "reply": reply, "sent": sent, "error": "" if reply else json.dumps(body, ensure_ascii=False)}


def probe_image(base_url: str, token: str, *, transport=None) -> dict[str, Any]:
    transport = transport or _http
    payload = {"prompt": "dot", "response_format": "b64_json", "n": 1, "size": "64x64"}
    try:
        body = transport("POST", base_url.rstrip("/") + "/v1/images/generations", payload, token)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    data = (body or {}).get("data") or []
    encoded = data[0].get("b64_json") if data else ""
    if not encoded:
        return {"ok": False, "error": "返回里没有图片字节"}
    return {"ok": True, "bytes": len(encoded), "error": ""}


def probe_h3(base_url: str, token: str, workflow_id: str, *, transport=None) -> dict[str, Any]:
    if workflow_id != "minimax_h3_803":
        raise GateError("workflow", "实例工作流 id 不是 minimax_h3_803 时不探测")
    header = h3_auth_header(token)
    transport = transport or _http
    url = base_url.rstrip("/") + "/api/v1/comfyui/workflows/minimax_h3_803"
    body = transport("GET", url, None, header)
    rules = (body or {}).get("input_rules")
    if not rules:
        return {"ok": False, "error": "没有 input_rules", "paid": False}
    return {"ok": True, "input_rules": rules, "paid": False, "auth": header}


def _http(method: str, url: str, payload: dict | None, token: str) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, method=method)
    request.add_header("Authorization", token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def verify_account(fields: dict[str, str], example: str, *, checker) -> dict[str, Any]:
    if not example:
        return {"status": "失败", "error": "缺少示例", "next": "在字段下方放一条可复制的假值"}
    missing = [name for name, value in fields.items() if not value]
    if missing:
        return {"status": "失败", "error": "未填写: " + ",".join(missing), "next": "补全必填项后再验证"}
    try:
        checker(fields)
    except Exception as exc:  # noqa: BLE001
        return {"status": "失败", "error": str(exc), "next": "对照示例检查密钥和地址"}
    return {"status": "可用", "error": "", "next": ""}


def verify_mcp(card: dict[str, Any], *, handshake) -> dict[str, Any]:
    """A normal MCP handshake that lists tools. The platform does not call Agno."""
    if not card.get("address"):
        return {"status": "失败", "error": "缺少地址", "next": "填写 stdio 命令或 HTTP 地址", "tools": []}
    try:
        tools = handshake(card["address"])
    except Exception as exc:  # noqa: BLE001
        return {"status": "失败", "error": str(exc), "next": "确认外部 MCP 进程已启动", "tools": []}
    if not isinstance(tools, list):
        return {"status": "失败", "error": "握手没有列出工具", "next": "让外部进程返回工具列表", "tools": []}
    return {"status": "可用", "error": "", "next": "", "tools": tools}


def may_create_segment_script(*, needs_external: bool, mcp_status: str | None) -> bool:
    if not needs_external:
        return True
    return mcp_status == "可用"


def record_benchmark(session: Session, instance: str, case_name: str, result: str, detail: str = "") -> None:
    if result not in {"passed", "failed", "不适用"}:
        raise GateError("benchmark", "结果只能是通过、失败或不适用")
    session.execute(
        text(
            """
            INSERT INTO llm_benchmarks (id, instance, case_name, result, detail)
            VALUES (:id, :instance, :case_name, :result, :detail)
            """
        ),
        {
            "id": "bench_" + uuid.uuid4().hex[:8],
            "instance": instance,
            "case_name": case_name,
            "result": result,
            "detail": detail,
        },
    )


def judge_benchmark(case_name: str, output: Any, *, visual: bool) -> str:
    if case_name == "extract_reference" and not visual:
        return "不适用"
    if case_name == "extract_reference":
        text_out = output if isinstance(output, str) else ""
        if text_out and "用途" not in text_out and "坐标" not in text_out:
            return "passed"
        return "failed"
    if case_name == "write_prompt":
        if isinstance(output, dict) and set(output) <= {"summary", "detailed_description", "overall_soundscape"}:
            if "subject_definitions" not in json.dumps(output):
                return "passed"
        return "failed"
    if case_name == "segment_script":
        if isinstance(output, list) and output and "video_task" not in json.dumps(output):
            needed = {"number", "duration", "cast", "scene", "action", "dialogue", "end_state"}
            if needed <= set(output[0]):
                return "passed"
        return "failed"
    return "failed"


def grid_sentence() -> str:
    return GRID_SENTENCE
