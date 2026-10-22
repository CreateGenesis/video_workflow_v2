"""OpenAI-compatible media endpoints: /v1/images/generations for images, /v1/audio/speech for music beds.

Many gateways speak these shapes, so this is the default "image-api" / "music-api" adapter.
"""

from __future__ import annotations

import base64

import httpx

from .base import Adapter, Outcome, OutputFile, ProviderError, TaskContext, TransientError, Usage


class _Http(Adapter):
    sync = True

    def _base(self) -> str:
        base = self.instance.base_url.rstrip("/")
        if not base:
            raise ProviderError("供应商地址没有配置")
        return base if base.endswith("/v1") else f"{base}/v1"

    def _post(self, path: str, body: dict) -> httpx.Response:
        try:
            with httpx.Client(timeout=httpx.Timeout(self.instance.timeout_seconds or 300, connect=15.0),
                              trust_env=False) as client:
                response = client.post(f"{self._base()}{path}", json=body, headers={
                    "Authorization": f"Bearer {self.instance.secret}", "User-Agent": "cvgen",
                })
        except httpx.HTTPError as exc:
            raise TransientError(f"请求失败：{exc}") from exc
        if response.status_code in {401, 403}:
            raise ProviderError("访问密钥被拒绝或余额不足")
        if response.status_code == 429 or response.status_code >= 500:
            raise TransientError(f"上游繁忙 HTTP {response.status_code}")
        if response.status_code >= 400:
            raise ProviderError(f"请求被拒绝 HTTP {response.status_code}：{response.text[:300]}")
        return response

    def _fetch(self, url: str) -> bytes:
        try:
            response = httpx.get(url, timeout=120, trust_env=False, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TransientError(f"下载失败：{exc}") from exc
        return response.content

    def probe(self) -> dict:
        try:
            response = httpx.get(f"{self._base()}/models", timeout=8, trust_env=False,
                                 headers={"Authorization": f"Bearer {self.instance.secret}"})
            return {"reachable": True, "status": response.status_code, "message": f"连通（HTTP {response.status_code}）"}
        except (httpx.HTTPError, ProviderError) as exc:
            return {"reachable": False, "message": f"无法连通：{exc}"}

    def list_models(self) -> list[str]:
        try:
            response = httpx.get(f"{self._base()}/models", timeout=15, trust_env=False,
                                 headers={"Authorization": f"Bearer {self.instance.secret}"})
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"模型列表没有返回：{exc}") from exc
        return sorted({str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict) and item.get("id")})


class OpenAIImageAdapter(_Http):
    kind = "image"
    protocol = "openai-images"

    def run(self, request: dict, ctx: TaskContext) -> Outcome:
        count = max(1, int(request.get("n") or 1))
        body = {
            "model": self.instance.model,
            "prompt": request.get("prompt") or "",
            "n": count,
            "size": request.get("size") or self.instance.options.get("size") or "1024x1024",
            **(request.get("params") or {}),
        }
        payload = self._post("/images/generations", body).json()
        files = []
        for index, item in enumerate(payload.get("data") or []):
            if not isinstance(item, dict):
                continue
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
            elif item.get("url"):
                raw = self._fetch(item["url"])
            else:
                continue
            suffix = ".jpg" if raw[:2] == b"\xff\xd8" else ".png"
            dest = ctx.workdir / f"image-{index}{suffix}"
            dest.write_bytes(raw)
            files.append(OutputFile(dest, "image/jpeg" if suffix == ".jpg" else "image/png", f"候选 {index + 1}"))
        if not files:
            raise ProviderError("生图接口没有返回图片")
        return Outcome(files=files, usage=[Usage("image", len(files))])

    def estimate(self, request: dict) -> list[Usage]:
        return [Usage("image", max(1, int(request.get("n") or 1)))]


class OpenAIAudioAdapter(_Http):
    kind = "music"
    protocol = "openai-audio"

    def run(self, request: dict, ctx: TaskContext) -> Outcome:
        body = {"model": self.instance.model, "input": request.get("lyrics") or request.get("prompt") or request.get("text") or ""}
        if not body["input"].strip():
            raise ProviderError("没有文本，不能生成音频")
        response = self._post("/audio/speech", body)
        raw = response.content
        if raw.lstrip()[:1] in {b"{", b"["}:
            payload = response.json()
            url = ((payload.get("data") or {}) if isinstance(payload.get("data"), dict) else {}).get("url")
            if not url:
                raise ProviderError("音频接口没有返回文件")
            raw = self._fetch(url)
        dest = ctx.workdir / "audio.wav"
        dest.write_bytes(raw)
        return Outcome(files=[OutputFile(dest, "audio/wav")], usage=[Usage("call", 1)])
