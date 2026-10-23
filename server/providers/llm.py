"""Large-language-model step: OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages.

All three return the same thing: a JSON object that should satisfy the requested schema. The
adapter asks the provider for structured output in the strictest form it supports; the executor
always re-validates against the original schema (providers drop range and length constraints).

Instance options:
- json_schema (capability, default true): native structured output; false falls back to
  JSON mode (OpenAI) or a strict tool the model is told to call (Anthropic).
- max_tokens (default 16000), max_tokens_param ("max_tokens" | "max_completion_tokens", OpenAI chat)
- effort (Anthropic, default "high"), fallbacks (Anthropic: "default" or "off"; default "default"
  on the official endpoint, "off" behind gateways)
"""

from __future__ import annotations

import copy
import json
import re

import httpx

from .base import Adapter, Outcome, ProviderError, TaskContext, TransientError, Usage

UNSUPPORTED_KEYWORDS = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems",
    "minProperties", "maxProperties", "$schema", "$id", "default", "examples", "format",
}
ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
TOOL_NAME = "submit_result"


def provider_schema(schema: dict) -> dict:
    """Strict-mode subset accepted by all three protocols.

    Every object lists all its properties as required and forbids extras; a property that was
    optional becomes nullable. Range/length keywords are removed here and enforced afterwards.
    """

    def walk(node):
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {key: walk(value) for key, value in node.items() if key not in UNSUPPORTED_KEYWORDS}
        kind = out.get("type")
        if isinstance(kind, list):
            variants = [{**{k: v for k, v in out.items() if k != "type"}, "type": item} for item in kind]
            return {"anyOf": [walk(variant) if variant["type"] != "null" else {"type": "null"} for variant in variants]}
        if kind == "object" or "properties" in out:
            properties = out.get("properties", {})
            required = set(node.get("required", []))
            for name, sub in list(properties.items()):
                if name not in required and not _nullable(sub):
                    properties[name] = {"anyOf": [sub, {"type": "null"}]}
            out["properties"] = properties
            out["required"] = list(properties)
            out["additionalProperties"] = False
        return out

    return walk(copy.deepcopy(schema))


def _nullable(schema: dict) -> bool:
    kind = schema.get("type")
    if kind == "null" or (isinstance(kind, list) and "null" in kind):
        return True
    return any(item.get("type") == "null" for item in schema.get("anyOf", []) if isinstance(item, dict))


def parse_json(text: str) -> object:
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"模型输出不是合法 JSON：{exc.msg}（第 {exc.pos} 个字符）") from exc


def _schema_note(schema: dict) -> str:
    return "只输出一个 JSON 对象，必须符合下面的 JSON Schema，不要输出其他文字：\n" + json.dumps(schema, ensure_ascii=False)


class _LLM(Adapter):
    kind = "llm"
    sync = True

    def _max_tokens(self, request: dict) -> int:
        return int(request.get("max_tokens") or self.instance.options.get("max_tokens") or 16000)

    def _native(self) -> bool:
        return bool(self.instance.capabilities.get("json_schema", True))

    def estimate(self, request: dict) -> list[Usage]:
        chars = len(request.get("system") or "") + sum(len(item.get("content", "")) for item in request.get("messages", []))
        return [Usage("token_in", max(1, chars // 2)), Usage("token_out", 2000)]


class _OpenAIBase(_LLM):
    def _base(self) -> str:
        base = (self.instance.base_url or "https://api.openai.com").rstrip("/")
        return base if re.search(r"/v\d+$", base) else f"{base}/v1"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.instance.secret}", "User-Agent": "cvgen"}

    def _post(self, path: str, body: dict) -> dict:
        timeout = httpx.Timeout(float(self.instance.timeout_seconds or 600), connect=15.0)
        try:
            with httpx.Client(timeout=timeout, trust_env=False) as client:
                response = client.post(f"{self._base()}{path}", json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise TransientError(f"请求失败：{exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientError(f"上游繁忙 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"返回不是 JSON（HTTP {response.status_code}）") from exc
        if response.status_code >= 400:
            message = (payload.get("error") or {}).get("message") if isinstance(payload.get("error"), dict) else payload.get("error")
            raise ProviderError(f"请求被拒绝 HTTP {response.status_code}：{message or response.text[:300]}")
        return payload

    def probe(self) -> dict:
        try:
            response = httpx.get(f"{self._base()}/models", headers=self._headers(), timeout=8, trust_env=False)
        except httpx.HTTPError as exc:
            return {"reachable": False, "message": f"无法连通：{exc}"}
        ok = response.status_code < 400
        return {"reachable": True, "status": response.status_code,
                "message": "连通，密钥有效" if ok else f"连通，但返回 HTTP {response.status_code}"}

    def list_models(self) -> list[str]:
        try:
            payload = httpx.get(f"{self._base()}/models", headers=self._headers(), timeout=15, trust_env=False).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"模型列表没有返回：{exc}") from exc
        return sorted({str(item["id"]) for item in payload.get("data", []) if isinstance(item, dict) and item.get("id")})


class OpenAIChatAdapter(_OpenAIBase):
    protocol = "openai-chat"

    def run(self, request: dict, ctx: TaskContext) -> Outcome:
        schema = provider_schema(request.get("schema") or {"type": "object"})
        name = request.get("schema_name") or "result"
        system = request.get("system") or ""
        if self._native():
            response_format = {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}
        else:
            response_format = {"type": "json_object"}
            system = f"{system}\n\n{_schema_note(schema)}".strip()
        messages = ([{"role": "system", "content": system}] if system else []) + list(request.get("messages") or [])
        body = {"model": self.instance.model, "messages": messages, "response_format": response_format}
        body[self.instance.options.get("max_tokens_param", "max_tokens")] = self._max_tokens(request)
        if request.get("temperature") is not None:
            body["temperature"] = request["temperature"]
        if request.get("seed") is not None:
            body["seed"] = request["seed"]
        payload = self._post("/chat/completions", body)
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if message.get("refusal"):
            raise ProviderError(f"模型拒绝：{message['refusal']}")
        if choice.get("finish_reason") == "length":
            raise ProviderError("输出被截断（达到 max_tokens），请调大 max_tokens")
        text = message.get("content") or ""
        usage = payload.get("usage") or {}
        return Outcome(
            data={"json": parse_json(text), "raw": text, "model": payload.get("model") or self.instance.model},
            usage=[Usage("token_in", usage.get("prompt_tokens", 0)), Usage("token_out", usage.get("completion_tokens", 0))],
        )


class OpenAIResponsesAdapter(_OpenAIBase):
    protocol = "openai-responses"

    def run(self, request: dict, ctx: TaskContext) -> Outcome:
        schema = provider_schema(request.get("schema") or {"type": "object"})
        name = request.get("schema_name") or "result"
        instructions = request.get("system") or ""
        if self._native():
            text_format = {"type": "json_schema", "name": name, "schema": schema, "strict": True}
        else:
            text_format = {"type": "json_object"}
            instructions = f"{instructions}\n\n{_schema_note(schema)}".strip()
        body = {
            "model": self.instance.model,
            "input": [{"role": item["role"], "content": item["content"]} for item in request.get("messages") or []],
            "text": {"format": text_format},
            "max_output_tokens": self._max_tokens(request),
        }
        if instructions:
            body["instructions"] = instructions
        if request.get("temperature") is not None:
            body["temperature"] = request["temperature"]
        payload = self._post("/responses", body)
        if payload.get("status") == "incomplete":
            reason = (payload.get("incomplete_details") or {}).get("reason") or ""
            raise ProviderError(f"输出不完整：{reason or '未知原因'}")
        text = payload.get("output_text") or ""
        if not text:
            for item in payload.get("output") or []:
                if item.get("type") != "message":
                    continue
                for part in item.get("content") or []:
                    if part.get("type") == "refusal":
                        raise ProviderError(f"模型拒绝：{part.get('refusal')}")
                    if part.get("type") == "output_text":
                        text += part.get("text") or ""
        if not text:
            raise ProviderError("模型没有返回文本")
        usage = payload.get("usage") or {}
        return Outcome(
            data={"json": parse_json(text), "raw": text, "model": payload.get("model") or self.instance.model},
            usage=[Usage("token_in", usage.get("input_tokens", 0)), Usage("token_out", usage.get("output_tokens", 0))],
        )


class AnthropicMessagesAdapter(_LLM):
    """Anthropic Messages API through the official SDK. base_url may point at a compatible gateway."""

    protocol = "anthropic-messages"

    def _official(self) -> bool:
        base = (self.instance.base_url or "").rstrip("/")
        return not base or base == "https://api.anthropic.com"

    def _client(self):
        import anthropic

        kwargs = {"api_key": self.instance.secret or None, "max_retries": 2,
                  "timeout": float(self.instance.timeout_seconds or 600)}
        if not self._official():
            kwargs["base_url"] = self.instance.base_url.rstrip("/")
        return anthropic.Anthropic(**kwargs)

    def _model(self) -> str:
        return self.instance.model or ANTHROPIC_DEFAULT_MODEL

    def run(self, request: dict, ctx: TaskContext) -> Outcome:
        import anthropic

        schema = provider_schema(request.get("schema") or {"type": "object"})
        options = self.instance.options
        kwargs: dict = {
            "model": self._model(),
            "max_tokens": self._max_tokens(request),
            "messages": list(request.get("messages") or []),
        }
        if request.get("system"):
            kwargs["system"] = request["system"]
        output_config: dict = {}
        effort = options.get("effort", "high")
        if effort and effort != "off":
            output_config["effort"] = effort
        if self._native():
            output_config["format"] = {"type": "json_schema", "schema": schema}
        else:
            kwargs["tools"] = [{
                "name": TOOL_NAME,
                "description": "提交最终结果。必须调用这个工具，参数就是结果本身。",
                "strict": True,
                "input_schema": schema,
            }]
            kwargs["system"] = f"{kwargs.get('system', '')}\n\n完成后调用 {TOOL_NAME} 工具提交结果，不要用文字回答。".strip()
        if output_config:
            kwargs["output_config"] = output_config
        if options.get("allow_sampling") and request.get("temperature") is not None:
            kwargs["temperature"] = request["temperature"]
        fallbacks = options.get("fallbacks", "default" if self._official() else "off")
        client = self._client()
        try:
            if fallbacks and fallbacks != "off":
                response = client.beta.messages.create(
                    **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks=fallbacks,
                )
            else:
                response = client.messages.create(**kwargs)
        except anthropic.APIConnectionError as exc:
            raise TransientError(f"连不上模型服务：{exc}") from exc
        except anthropic.RateLimitError as exc:
            raise TransientError("模型服务限流，稍后重试") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientError(f"模型服务异常 HTTP {exc.status_code}") from exc
            raise ProviderError(f"请求被拒绝 HTTP {exc.status_code}：{exc.message}") from exc
        finally:
            client.close()

        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ProviderError(f"模型拒绝了这个请求（{category or '未注明类别'}）")
        if stop_reason == "max_tokens":
            raise ProviderError("输出被截断（达到 max_tokens），请调大 max_tokens")
        result, raw = None, ""
        for block in response.content:
            block_type = getattr(block, "type", "")
            if block_type == "tool_use" and getattr(block, "name", "") == TOOL_NAME:
                result = getattr(block, "input", None)
                raw = json.dumps(result, ensure_ascii=False)
                break
            if block_type == "text" and self._native():
                raw = getattr(block, "text", "")
                result = parse_json(raw)
                break
        if result is None:
            raise ProviderError("模型没有返回结构化结果")
        usage = getattr(response, "usage", None)
        return Outcome(
            data={"json": result, "raw": raw, "model": getattr(response, "model", self._model())},
            usage=[Usage("token_in", getattr(usage, "input_tokens", 0) or 0),
                   Usage("token_out", getattr(usage, "output_tokens", 0) or 0)],
        )

    def probe(self) -> dict:
        import anthropic

        client = self._client()
        try:
            client.models.retrieve(self._model())
            return {"reachable": True, "message": f"连通，模型 {self._model()} 可用"}
        except anthropic.APIConnectionError as exc:
            return {"reachable": False, "message": f"无法连通：{exc}"}
        except anthropic.APIStatusError as exc:
            return {"reachable": True, "status": exc.status_code, "message": f"连通，但返回 HTTP {exc.status_code}"}
        finally:
            client.close()

    def list_models(self) -> list[str]:
        import anthropic

        client = self._client()
        try:
            return sorted(model.id for model in client.models.list())
        except anthropic.APIError as exc:
            raise ProviderError(f"模型列表没有返回：{exc}") from exc
        finally:
            client.close()
