"""AutoDL hosted ComfyUI workflows: MiniMax H3 video and IndexTTS2 speech. Both bill per submission.

Submissions are never retried blindly: a failed or ambiguous submit raises SubmissionUnknown, and
the engine parks the task for a person to resolve.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import httpx

from .base import (
    Adapter, Outcome, OutputFile, Progress, ProviderError, SubmissionUnknown, TaskContext, TransientError, Usage,
)

IMAGE_SLOTS = 9
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/flac", "audio/x-wav", "audio/mp4"}


def _data_url(path: Path, allowed: set[str]) -> str:
    mime = mimetypes.guess_type(path.name)[0] or ""
    if mime not in allowed:
        raise ProviderError(f"{path.name} 的类型 {mime or '未知'} 不被接受")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


class _AutoDL(Adapter):
    sync = False
    poll_interval = 15.0
    workflow_path = ""

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0), trust_env=False, headers={
            "Authorization": f"Bearer {self.instance.secret}",
            "Accept": "application/json",
            "User-Agent": "cvgen",
        })

    def _base(self) -> str:
        return (self.instance.base_url or "https://www.autodl.art").rstrip("/")

    def _submit_body(self, body: dict) -> dict:
        url = f"{self._base()}/api/v1/comfyui/comfyui_workflow/{self.workflow_path}"
        try:
            with self._client() as client:
                response = client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise SubmissionUnknown(f"提交时网络中断，不知道上游是否已受理：{exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise SubmissionUnknown(f"提交返回不是 JSON（HTTP {response.status_code}）") from exc
        if response.status_code == 401:
            raise ProviderError("访问密钥被拒绝")
        if response.status_code == 403:
            raise ProviderError("没有权限或余额不足")
        if response.status_code != 200 or payload.get("code") not in (None, "Success"):
            raise ProviderError(f"提交被拒绝 HTTP {response.status_code}：{payload.get('msg') or payload.get('code')}")
        task_id = (payload.get("data") or {}).get("task_id")
        if not task_id:
            raise SubmissionUnknown("提交返回里没有 task_id")
        return {"task_id": task_id, "request_id": payload.get("request_id")}

    def _query(self, task_id: str) -> dict:
        url = f"{self._base()}/api/v1/comfyui/comfyui_workflow/result/{task_id}"
        try:
            with self._client() as client:
                response = client.get(url)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TransientError(f"查询失败：{exc}") from exc
        if response.status_code == 401:
            raise TransientError("查询时访问密钥被拒绝")
        if response.status_code >= 500:
            raise TransientError(f"查询返回 HTTP {response.status_code}")
        data = payload.get("data") or {}
        results = data.get("results") or []
        url_found = next((item["url"] for item in results if isinstance(item, dict) and item.get("url")), "")
        return {"status": str(data.get("status") or "").lower(), "url": url_found, "msg": payload.get("msg") or ""}

    def _download(self, url: str, dest: Path) -> Path:
        partial = dest.with_suffix(dest.suffix + ".partial")
        try:
            with httpx.stream("GET", url, timeout=httpx.Timeout(300.0, connect=15.0), trust_env=False,
                              follow_redirects=True) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 20):
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise TransientError(f"下载失败：{exc}") from exc
        partial.replace(dest)
        return dest

    def _poll(self, ref: dict, ctx: TaskContext, dest_name: str, mime: str, usage: list[Usage]) -> Progress | Outcome:
        state = self._query(ref["task_id"])
        if state["url"] or state["status"] in {"success", "succeeded", "completed"}:
            if not state["url"]:
                raise ProviderError("上游报告完成但没有返回文件")
            path = self._download(state["url"], ctx.workdir / dest_name)
            return Outcome(files=[OutputFile(path, mime)], usage=usage, data={"upstream_status": state["status"]})
        if state["status"] in {"failed", "error", "canceled", "cancelled"}:
            raise ProviderError(state["msg"] or "上游任务失败")
        return Progress(message=state["status"] or "排队中")

    def probe(self) -> dict:
        try:
            with self._client() as client:
                response = client.get(self._base())
            return {"reachable": True, "status": response.status_code, "message": f"连通（HTTP {response.status_code}）"}
        except httpx.HTTPError as exc:
            return {"reachable": False, "message": f"无法连通：{exc}"}


class AutoDLH3Adapter(_AutoDL):
    kind = "video"
    protocol = "autodl-h3"

    @property
    def workflow_path(self) -> str:  # type: ignore[override]
        return self.instance.model or "minimax_h3_zm_u24"

    def submit(self, request: dict, ctx: TaskContext) -> dict:
        prompt = (request.get("prompt") or "").strip()
        if not prompt:
            raise ProviderError("提示词为空")
        duration = int(request.get("duration") or 5)
        if not 1 <= duration <= 15:
            raise ProviderError("时长必须是 1 到 15 的整数")
        refs = request.get("references") or []
        if not refs:
            raise ProviderError("这个 H3 工作流没有参考图就不能提交")
        if len(refs) > IMAGE_SLOTS:
            raise ProviderError(f"参考图最多 {IMAGE_SLOTS} 张")
        body: dict = {"prompt": prompt, "duration": duration, "resolution": request.get("resolution") or "768p横"}
        for index, ref in enumerate(refs):
            body[f"ref_image_{index}"] = _data_url(Path(ref["path"]), IMAGE_TYPES)
        if request.get("seed") is not None:
            body["seed"] = int(request["seed"])
        accepted = self._submit_body(body)
        return {**accepted, "duration": duration}

    def poll(self, ref: dict, ctx: TaskContext) -> Progress | Outcome:
        return self._poll(ref, ctx, "h3.mp4", "video/mp4", [Usage("video_second", int(ref.get("duration") or 5))])

    def estimate(self, request: dict) -> list[Usage]:
        return [Usage("video_second", int(request.get("duration") or 5))]


class AutoDLIndexTTSAdapter(_AutoDL):
    kind = "tts"
    protocol = "autodl-indextts"

    @property
    def workflow_path(self) -> str:  # type: ignore[override]
        return self.instance.model or "indextts2-v1"

    def submit(self, request: dict, ctx: TaskContext) -> dict:
        text = (request.get("text") or "").strip()
        if not text:
            raise ProviderError("台词为空")
        speaker = request.get("speaker")
        if not speaker:
            raise ProviderError("缺少音色参考音频")
        voice = request.get("voice") or {}
        body = {
            "prompt_text": text,
            "prompt_simple": _data_url(Path(speaker), AUDIO_TYPES),
            "emo_control_method": voice.get("method") or "与音色参考音频相同",
        }
        for name in ("happy", "angry", "sad", "afraid", "disgusted", "melancholic", "surprised", "calm"):
            if voice.get(name) not in (None, ""):
                body[f"emo_{name}"] = float(voice[name])
        return self._submit_body(body)

    def poll(self, ref: dict, ctx: TaskContext) -> Progress | Outcome:
        return self._poll(ref, ctx, "speech.wav", "audio/wav", [Usage("call", 1)])
