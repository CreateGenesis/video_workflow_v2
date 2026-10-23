"""The three LLM protocols against a local fake server: request shapes, parsing, errors."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server.providers.base import Instance, ProviderError, TaskContext, TransientError
from server.providers.llm import (
    AnthropicMessagesAdapter, OpenAIChatAdapter, OpenAIResponsesAdapter, provider_schema,
)

SCHEMA = {
    "type": "object",
    "required": ["title", "beats"],
    "properties": {
        "title": {"type": "string", "maxLength": 10},
        "beats": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string", "minLength": 2}},
        "note": {"type": ["string", "null"]},
        "mood": {"type": "string"},
    },
}
RESULT = {"title": "雪原", "beats": ["跪下", "抬头"], "note": None, "mood": "冷"}


class Fake(BaseHTTPRequestHandler):
    seen: list = []
    mode = "ok"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append({"path": self.path, "body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
        if Fake.mode == "429":
            return self._send(429, {"error": {"message": "slow down"}})
        if Fake.mode == "400":
            return self._send(400, {"error": {"type": "invalid_request_error", "message": "bad schema"},
                                    "type": "error"})
        text = json.dumps(RESULT, ensure_ascii=False)
        if self.path.endswith("/chat/completions"):
            finish = "length" if Fake.mode == "truncated" else "stop"
            return self._send(200, {"model": body["model"], "choices": [{"finish_reason": finish, "message": {
                "role": "assistant", "content": text}}], "usage": {"prompt_tokens": 11, "completion_tokens": 22}})
        if self.path.endswith("/responses"):
            return self._send(200, {"model": body["model"], "status": "completed", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}],
                "usage": {"input_tokens": 12, "output_tokens": 23}})
        if self.path.endswith("/v1/messages"):
            if Fake.mode == "refusal":
                return self._send(200, {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                        "content": [], "stop_reason": "refusal", "stop_sequence": None,
                                        "stop_details": {"type": "refusal", "category": "cyber", "explanation": "x"},
                                        "usage": {"input_tokens": 5, "output_tokens": 0}})
            content = [{"type": "text", "text": text}]
            if body.get("tools"):
                content = [{"type": "tool_use", "id": "toolu_1", "name": "submit_result", "input": RESULT}]
            return self._send(200, {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                    "content": content, "stop_reason": "end_turn", "stop_sequence": None,
                                    "usage": {"input_tokens": 13, "output_tokens": 24}})
        return self._send(404, {"error": "no route"})

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def fake():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(autouse=True)
def reset():
    Fake.seen.clear()
    Fake.mode = "ok"


def _request() -> dict:
    return {"system": "只输出 JSON", "messages": [{"role": "user", "content": "写分镜"}], "schema": SCHEMA,
            "schema_name": "script", "temperature": 0.5}


def _ctx(tmp_path) -> TaskContext:
    return TaskContext(task_id="task_x", workdir=tmp_path)


def test_provider_schema_is_strict_subset():
    strict = provider_schema(SCHEMA)
    assert strict["additionalProperties"] is False
    assert strict["required"] == ["title", "beats", "note", "mood"]
    assert "maxLength" not in strict["properties"]["title"]
    assert "minItems" not in strict["properties"]["beats"] and "minLength" not in strict["properties"]["beats"]["items"]
    assert strict["properties"]["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert strict["properties"]["mood"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}


def test_openai_chat(fake, tmp_path):
    adapter = OpenAIChatAdapter(Instance(name="llm.chat", kind="llm", protocol="openai-chat", base_url=fake,
                                         secret="sk-test", model="gpt-x"))
    outcome = adapter.run(_request(), _ctx(tmp_path))
    sent = Fake.seen[-1]
    assert sent["path"] == "/v1/chat/completions" and sent["headers"]["authorization"] == "Bearer sk-test"
    assert sent["body"]["response_format"]["type"] == "json_schema"
    assert sent["body"]["response_format"]["json_schema"]["strict"] is True
    assert sent["body"]["messages"][0] == {"role": "system", "content": "只输出 JSON"}
    assert outcome.data["json"] == RESULT
    assert [(item.unit, item.quantity) for item in outcome.usage] == [("token_in", 11), ("token_out", 22)]


def test_openai_chat_json_mode_fallback_and_errors(fake, tmp_path):
    adapter = OpenAIChatAdapter(Instance(name="llm.gw", kind="llm", protocol="openai-chat", base_url=f"{fake}/v1",
                                         model="m", capabilities={"json_schema": False}))
    adapter.run(_request(), _ctx(tmp_path))
    body = Fake.seen[-1]["body"]
    assert body["response_format"] == {"type": "json_object"} and "JSON Schema" in body["messages"][0]["content"]
    Fake.mode = "truncated"
    with pytest.raises(ProviderError, match="截断"):
        adapter.run(_request(), _ctx(tmp_path))
    Fake.mode = "429"
    with pytest.raises(TransientError):
        adapter.run(_request(), _ctx(tmp_path))
    Fake.mode = "400"
    with pytest.raises(ProviderError, match="bad schema"):
        adapter.run(_request(), _ctx(tmp_path))


def test_openai_responses(fake, tmp_path):
    adapter = OpenAIResponsesAdapter(Instance(name="llm.resp", kind="llm", protocol="openai-responses",
                                              base_url=fake, model="gpt-y"))
    outcome = adapter.run(_request(), _ctx(tmp_path))
    body = Fake.seen[-1]["body"]
    assert Fake.seen[-1]["path"] == "/v1/responses"
    assert body["text"]["format"]["type"] == "json_schema" and body["instructions"] == "只输出 JSON"
    assert body["input"] == [{"role": "user", "content": "写分镜"}]
    assert outcome.data["json"] == RESULT and outcome.usage[1].quantity == 23


def test_anthropic_messages_structured_output(fake, tmp_path):
    adapter = AnthropicMessagesAdapter(Instance(name="llm.claude", kind="llm", protocol="anthropic-messages",
                                                base_url=fake, secret="sk-ant-test"))
    outcome = adapter.run(_request(), _ctx(tmp_path))
    sent = Fake.seen[-1]
    body = sent["body"]
    assert sent["path"] == "/v1/messages"
    assert "sk-ant-test" in (sent["headers"].get("x-api-key", "") + sent["headers"].get("authorization", ""))
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["effort"] == "high"
    assert "temperature" not in body and "fallbacks" not in body and "tool_choice" not in body
    assert body["system"] == "只输出 JSON"
    assert outcome.data["json"] == RESULT and outcome.usage[0].quantity == 13


def test_anthropic_strict_tool_fallback_and_refusal(fake, tmp_path):
    adapter = AnthropicMessagesAdapter(Instance(name="llm.gw", kind="llm", protocol="anthropic-messages", base_url=fake,
                                                model="claude-sonnet-5-5", capabilities={"json_schema": False},
                                                options={"effort": "off"}))
    outcome = adapter.run(_request(), _ctx(tmp_path))
    body = Fake.seen[-1]["body"]
    assert body["tools"][0]["strict"] is True and body["tools"][0]["name"] == "submit_result"
    assert "tool_choice" not in body and "output_config" not in body
    assert outcome.data["json"] == RESULT
    Fake.mode = "refusal"
    with pytest.raises(ProviderError, match="cyber"):
        adapter.run(_request(), _ctx(tmp_path))
