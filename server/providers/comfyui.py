"""Self-hosted ComfyUI: one GPU machine per instance, driven over its HTTP API.

The worker uploads reference images (/upload/image), fills a template's API-format graph, submits it
(/prompt), polls /history and /queue, and pulls the output files back through /view. ComfyUI has no
auth of its own; if instance.secret is set it is sent as a Bearer token for a reverse proxy in front.

Template (library asset of kind comfy_template):
    {"graph": {node_id: {"class_type": ..., "inputs": {...}}},   # ComfyUI API format
     "bindings": {logical_name: "<node_id>.inputs.<field>"},
     "outputs": [node_id, ...],                                    # nodes whose files we download
     "requires": {"nodes": [class_type, ...], "models": {folder: [filename, ...]}},
     "options": {"fps": 16, "length_plus_one": false, "expected_seconds": 600}}

Bindings. Each binding names an existing input field of an existing node; a path that is not in the
graph is a ProviderError. The adapter fills these logical names:
- prompt:            the request prompt (request "text" for tts-style requests)
- image, image_0, image_1, ...: uploaded file names of request references, in order ("image" == "image_0").
                     Only bound slots are uploaded; a bound slot without a reference is a ProviderError.
- seed:              the request seed, else a random one (recorded in the returned ref)
- duration:          seconds; length: duration * fps (+1 if options.length_plus_one); fps: options.fps (16)
- width, height:     from the resolution tier (480p横 = 854x480 ... 768p(1:1) = 768x768)
- any other key of request["params"] that has a binding. Params cannot override the names above;
  params without a binding are ignored.
The template is never mutated; the graph is deep-copied per submission.

Dedup: the prompt_id is a uuid5 of the task id and extra_data carries {"cvgen_task": task_id}, so find()
can locate a job after a crash. Servers that ignore a client-supplied prompt_id get looked up by extra_data.
"""

from __future__ import annotations

import copy
import mimetypes
import random
import re
import time
import uuid
from pathlib import Path

import httpx

from .base import (
    Adapter, Outcome, OutputFile, Progress, ProviderError, SubmissionUnknown, TaskContext, TransientError, Usage,
)

SIZES = {
    "480p横": (854, 480), "480p竖": (480, 854), "768p横": (1366, 768),
    "768p竖": (768, 1366), "480p(1:1)": (480, 480), "768p(1:1)": (768, 768),
}
RESERVED = {"prompt", "image", "seed", "duration", "length", "fps", "width", "height"}
IMAGE_SLOT = re.compile(r"image(?:_(\d+))?")
OUTPUT_KEYS = ("images", "gifs", "videos", "audio")
LONG = httpx.Timeout(300.0, connect=10.0)
HISTORY_SCAN = 200


def prompt_id_for(task_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"cvgen-task:{task_id}"))


def _target(graph: dict, path: str) -> tuple[dict, str]:
    node_id, sep, name = str(path).partition(".inputs.")
    node = graph.get(node_id)
    inputs = node.get("inputs") if isinstance(node, dict) else None
    if not sep or not isinstance(inputs, dict) or name not in inputs:
        raise ProviderError(f"模板绑定 {path} 在工作流里找不到（应为 节点id.inputs.字段，且节点和字段都存在）")
    return inputs, name


def _image_slots(bindings: dict) -> list[int]:
    slots = set()
    for name in bindings:
        match = IMAGE_SLOT.fullmatch(name)
        if match:
            slots.add(int(match.group(1) or 0))
    return sorted(slots)


def binding_values(request: dict, template: dict, seed: int) -> dict:
    """Logical name -> value for every name the adapter fills, except the uploaded images."""
    options = template.get("options") or {}
    fps = int(options.get("fps") or 16)
    values = {key: value for key, value in (request.get("params") or {}).items() if key not in RESERVED}
    values.update(prompt=request.get("prompt") or request.get("text") or "", seed=seed, fps=fps)
    if request.get("duration") is not None:
        seconds = int(request["duration"])
        values.update(duration=seconds, length=seconds * fps + (1 if options.get("length_plus_one") else 0))
    resolution = request.get("resolution")
    if resolution:
        if resolution not in SIZES:
            raise ProviderError(f"分辨率 {resolution} 不在档位里")
        values["width"], values["height"] = SIZES[resolution]
    return values


def image_values(images: dict[int, str]) -> dict:
    values = {f"image_{index}": name for index, name in images.items()}
    if 0 in images:
        values["image"] = images[0]
    return values


def fill_graph(template: dict, values: dict) -> dict:
    """Deep copy of the template graph with bound inputs replaced. Every binding path is checked."""
    graph = copy.deepcopy(template.get("graph") or {})
    for name, path in (template.get("bindings") or {}).items():
        inputs, field_name = _target(graph, path)
        if name in values:
            inputs[field_name] = values[name]
    return graph


def _error_summary(payload: dict) -> str:
    error = payload.get("error")
    parts = [(error.get("message") or error.get("type") or "") if isinstance(error, dict) else str(error or "")]
    for node_id, info in (payload.get("node_errors") or {}).items():
        for item in (info or {}).get("errors") or []:
            detail = f"{item.get('message') or ''} {item.get('details') or ''}".strip()
            parts.append(f"节点 {node_id}（{info.get('class_type') or ''}）：{detail}")
    return "；".join(part for part in parts if part)[:600] or "未知错误"


def _failure(entry: dict) -> str | None:
    """None if the history entry finished cleanly, else a readable reason."""
    status = entry.get("status") or {}
    messages = status.get("messages") or []
    for event, data in (item for item in messages if isinstance(item, (list, tuple)) and len(item) == 2):
        if event == "execution_error":
            data = data or {}
            where = f"节点 {data.get('node_id')} {data.get('node_type') or ''}".strip()
            return f"ComfyUI 执行出错（{where}）：{str(data.get('exception_message') or '').strip()}"
        if event == "execution_interrupted":
            return "任务在 ComfyUI 上被中断"
    if status.get("status_str") == "error" or status.get("completed") is False:
        return "ComfyUI 报告任务失败"
    return None


def _queue_entries(queue: object) -> tuple[list, list]:
    queue = queue if isinstance(queue, dict) else {}
    running = [item for item in queue.get("queue_running") or [] if isinstance(item, list) and len(item) > 1]
    pending = [item for item in queue.get("queue_pending") or [] if isinstance(item, list) and len(item) > 1]
    return running, sorted(pending, key=lambda item: item[0])  # the pending list is a heap, not sorted


class ComfyUIAdapter(Adapter):
    protocol = "comfyui"
    sync = False
    poll_interval = 5.0

    def __init__(self, instance):
        super().__init__(instance)
        self.kind = instance.kind or "video"

    # -- plumbing -------------------------------------------------------------------------------

    def _base(self) -> str:
        base = (self.instance.base_url or "").rstrip("/")
        if not base:
            raise ProviderError("ComfyUI 地址没有配置")
        return base

    def _client(self) -> httpx.Client:
        headers = {"User-Agent": "cvgen"}
        if self.instance.secret:
            headers["Authorization"] = f"Bearer {self.instance.secret}"
        return httpx.Client(base_url=self._base(), timeout=httpx.Timeout(60.0, connect=10.0),
                            trust_env=False, headers=headers)

    def _client_id(self) -> str:
        return f"cvgen-{self.instance.name}"

    def _get_json(self, client: httpx.Client, path: str, **params) -> object:
        try:
            response = client.get(path, params=params or None)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TransientError(f"ComfyUI 请求 {path} 失败：{exc}") from exc

    def _post_json(self, client: httpx.Client, path: str, body: dict) -> None:
        try:
            client.post(path, json=body).raise_for_status()
        except httpx.HTTPError as exc:
            raise TransientError(f"ComfyUI 请求 {path} 失败：{exc}") from exc

    def _history(self, client: httpx.Client, prompt_id: str) -> dict | None:
        payload = self._get_json(client, f"/history/{prompt_id}")
        entry = payload.get(prompt_id) if isinstance(payload, dict) else None
        return entry if isinstance(entry, dict) else None

    def _queue_state(self, client: httpx.Client, prompt_id: str) -> tuple[str | None, int]:
        """("running", 0) / ("pending", position from 1) / (None, 0)."""
        running, pending = _queue_entries(self._get_json(client, "/queue"))
        if any(item[1] == prompt_id for item in running):
            return "running", 0
        for position, item in enumerate(pending, start=1):
            if item[1] == prompt_id:
                return "pending", position
        return None, 0

    # -- submission -----------------------------------------------------------------------------

    def _upload(self, client: httpx.Client, path: Path, name: str) -> str:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            with path.open("rb") as handle:
                response = client.post("/upload/image", files={"image": (name, handle, mime)},
                                       data={"overwrite": "true", "type": "input"}, timeout=LONG)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TransientError(f"上传参考图 {path.name} 失败：{exc}") from exc
        uploaded = payload.get("name") or name
        return f"{payload['subfolder']}/{uploaded}" if payload.get("subfolder") else uploaded

    def _upload_references(self, client: httpx.Client, request: dict, slots: list[int],
                           ctx: TaskContext) -> dict[int, str]:
        references = request.get("references") or []
        if slots and slots[-1] >= len(references):
            raise ProviderError(f"模板需要 {slots[-1] + 1} 张参考图，请求里只有 {len(references)} 张")
        images = {}
        for index in slots:
            item = references[index]
            path = Path(item["path"] if isinstance(item, dict) else item)
            if not path.is_file():
                raise ProviderError(f"参考图 {path} 不存在")
            images[index] = self._upload(client, path, f"{ctx.task_id}-{index}{path.suffix}")
            ctx.heartbeat()
        return images

    def _stop(self, client: httpx.Client, prompt_id: str) -> bool:
        state, _ = self._queue_state(client, prompt_id)
        if state == "pending":
            self._post_json(client, "/queue", {"delete": [prompt_id]})
            state, _ = self._queue_state(client, prompt_id)  # it may have started in the meantime
            if state is None:
                return True
        if state == "running":
            self._post_json(client, "/interrupt", {"prompt_id": prompt_id})
            return True
        return False

    def _post_prompt(self, client: httpx.Client, body: dict) -> dict:
        try:
            response = client.post("/prompt", json=body)
        except httpx.HTTPError as exc:
            raise SubmissionUnknown(f"提交到 ComfyUI 时网络中断，不知道是否已入队：{exc}") from exc
        if response.status_code in {401, 403}:
            raise ProviderError("ComfyUI 前面的反向代理拒绝了访问令牌")
        try:
            payload = response.json()
        except ValueError as exc:
            if 400 <= response.status_code < 500:
                raise ProviderError(f"ComfyUI 拒绝了提交 HTTP {response.status_code}：{response.text[:300]}") from exc
            raise SubmissionUnknown(f"提交返回不是 JSON（HTTP {response.status_code}）") from exc
        if response.status_code >= 500:
            raise SubmissionUnknown(f"提交返回 HTTP {response.status_code}，不知道是否已入队")
        if response.status_code >= 400 or payload.get("node_errors"):
            if response.status_code == 200 and payload.get("prompt_id"):
                try:  # a partly valid graph is queued anyway; take it back
                    self._stop(client, payload["prompt_id"])
                except TransientError:
                    pass
            raise ProviderError(f"ComfyUI 拒绝了工作流：{_error_summary(payload)}")
        if not payload.get("prompt_id"):
            raise SubmissionUnknown("提交返回里没有 prompt_id")
        return payload

    def submit(self, request: dict, ctx: TaskContext) -> dict:
        template = request.get("template")
        if not isinstance(template, dict) or not isinstance(template.get("graph"), dict):
            raise ProviderError("ComfyUI 任务需要模板（graph、bindings、outputs）")
        bindings = template.get("bindings") or {}
        for path in bindings.values():
            _target(template["graph"], path)
        seed = int(request["seed"]) if request.get("seed") is not None else random.randrange(2**31)
        our_id = prompt_id_for(ctx.task_id)
        values = binding_values(request, template, seed)
        with self._client() as client:
            values.update(image_values(self._upload_references(client, request, _image_slots(bindings), ctx)))
            graph = fill_graph(template, values)
            try:  # a retry reuses our prompt_id; drop the earlier attempt's history so poll can't read it
                client.post("/history", json={"delete": [our_id]})
            except httpx.HTTPError:
                pass
            ref = {"client_id": self._client_id(), "seed": seed, "submitted_at": time.time(),
                   "outputs": [str(node_id) for node_id in template.get("outputs") or []]}
            payload = self._post_prompt(client, {
                "prompt": graph, "client_id": ref["client_id"], "prompt_id": our_id,
                "extra_data": {"cvgen_task": ctx.task_id, "cvgen_ref": ref},
            })
        if payload["prompt_id"] != our_id:
            ctx.log(f"这台 ComfyUI 不接受客户端指定的 prompt_id，改用服务器分配的 {payload['prompt_id']}")
        return {"prompt_id": payload["prompt_id"], **ref}

    # -- progress and results -------------------------------------------------------------------

    def _download(self, client: httpx.Client, item: dict, dest: Path) -> Path:
        params = {"filename": item["filename"], "subfolder": item.get("subfolder") or "",
                  "type": item.get("type") or "output"}
        partial = dest.with_name(dest.name + ".partial")
        try:
            with client.stream("GET", "/view", params=params, timeout=LONG) as response:
                response.raise_for_status()
                with partial.open("wb") as handle:
                    for chunk in response.iter_bytes(1 << 20):
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise TransientError(f"下载产物 {item['filename']} 失败：{exc}") from exc
        partial.replace(dest)
        return dest

    def _collect(self, client: httpx.Client, entry: dict, ref: dict, ctx: TaskContext) -> list[OutputFile]:
        outputs = entry.get("outputs") or {}
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        files = []
        for node_id in ref.get("outputs") or list(outputs):
            for key in OUTPUT_KEYS:
                for item in (outputs.get(str(node_id)) or {}).get(key) or []:
                    if not isinstance(item, dict) or not item.get("filename"):
                        continue
                    dest = ctx.workdir / f"{node_id}-{Path(item['filename']).name}"
                    self._download(client, item, dest)
                    files.append(OutputFile(dest, mimetypes.guess_type(dest.name)[0] or "application/octet-stream"))
                    ctx.heartbeat()
        if not files:
            wanted = ", ".join(map(str, ref.get("outputs") or [])) or "（全部）"
            raise ProviderError(f"ComfyUI 报告完成，但输出节点 {wanted} 没有文件")
        return files

    def poll(self, ref: dict, ctx: TaskContext) -> Progress | Outcome:
        prompt_id = ref["prompt_id"]
        with self._client() as client:
            entry = self._history(client, prompt_id)
            if entry is None:
                state, position = self._queue_state(client, prompt_id)
                if state == "running":
                    return Progress(message="渲染中")
                if state == "pending":
                    return Progress(message=f"排队第 {position} 位")
                raise TransientError(f"ComfyUI 上的任务 {prompt_id} 不在队列也不在历史里（机器可能重启过）")
            reason = _failure(entry)
            if reason:
                raise ProviderError(reason)
            files = self._collect(client, entry, ref, ctx)
        seconds = max(0.0, time.time() - float(ref.get("submitted_at") or time.time()))
        return Outcome(files=files, usage=[Usage("gpu_second", round(seconds, 1))], data={"prompt_id": prompt_id})

    def cancel(self, ref: dict, ctx: TaskContext) -> bool:
        with self._client() as client:
            return self._stop(client, ref["prompt_id"])

    def find(self, ctx: TaskContext) -> dict | None:
        our_id = prompt_id_for(ctx.task_id)

        def ours(item: list) -> bool:
            extra = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
            return item[1] == our_id or extra.get("cvgen_task") == ctx.task_id

        with self._client() as client:
            running, pending = _queue_entries(self._get_json(client, "/queue"))
            candidates = [*running, *pending]
            entry = self._history(client, our_id)
            if entry:
                candidates.append(entry.get("prompt") or [])
            history = self._get_json(client, "/history", max_items=HISTORY_SCAN)
            newest_first = reversed(list(history.values())) if isinstance(history, dict) else []
            candidates += [value.get("prompt") or [] for value in newest_first if isinstance(value, dict)]
        item = next((item for item in candidates if isinstance(item, list) and len(item) > 1 and ours(item)), None)
        return self._ref_from(item) if item else None

    def _ref_from(self, item: list) -> dict:
        extra = item[3] if len(item) > 3 and isinstance(item[3], dict) else {}
        saved = extra.get("cvgen_ref") or {}
        submitted = saved.get("submitted_at") or (extra.get("create_time") or time.time() * 1000) / 1000
        outputs = saved.get("outputs") or [str(node_id) for node_id in (item[4] if len(item) > 4 else [])]
        client_id = saved.get("client_id") or extra.get("client_id") or self._client_id()
        return {"prompt_id": item[1], "client_id": client_id, "seed": saved.get("seed"),
                "submitted_at": submitted, "outputs": outputs}

    # -- environment ----------------------------------------------------------------------------

    def probe(self) -> dict:
        started = time.monotonic()
        try:
            with self._client() as client:
                response = client.get("/system_stats")
            elapsed = int((time.monotonic() - started) * 1000)
            if response.status_code in {401, 403}:
                return {"reachable": False, "message": "反向代理拒绝了访问令牌", "latency_ms": elapsed, "devices": []}
            response.raise_for_status()
            stats = response.json()
        except (httpx.HTTPError, ValueError, ProviderError) as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            return {"reachable": False, "message": f"无法连通：{exc}", "latency_ms": elapsed, "devices": []}
        devices = stats.get("devices") or []
        version = (stats.get("system") or {}).get("comfyui_version") or "未知版本"
        return {"reachable": True, "message": f"连通，ComfyUI {version}，{len(devices)} 块设备",
                "latency_ms": elapsed, "devices": devices, "version": version}

    def _listing(self, client: httpx.Client, path: str) -> set[str] | None:
        """/models or /models/<folder> as a set of names; None when this ComfyUI answers 404."""
        try:
            response = client.get(path)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return {str(name).replace("\\", "/") for name in response.json()}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise TransientError(f"ComfyUI 请求 {path} 失败：{exc}") from exc

    def _missing_models(self, client: httpx.Client, models: dict | list) -> list[str]:
        if isinstance(models, list):  # names without folders: look through every model folder
            folders = self._listing(client, "/models") if models else None
            if folders is None:
                return []
            found = set().union(*(self._listing(client, f"/models/{folder}") or set() for folder in folders))
            return [f"缺少模型 {name}" for name in models if str(name).replace("\\", "/") not in found]
        missing = []
        for folder, names in models.items():
            found = self._listing(client, f"/models/{folder}")
            if found is not None:
                missing += [f"缺少模型 {folder}/{name}" for name in names if str(name).replace("\\", "/") not in found]
        return missing

    def check_template(self, template: dict) -> list[str]:
        requires = template.get("requires") or {}
        graph = template.get("graph") or {}
        wanted = [*(requires.get("nodes") or []),
                  *(node.get("class_type") for node in graph.values() if isinstance(node, dict))]
        with self._client() as client:
            available = self._get_json(client, "/object_info")
            missing = [f"缺少节点 {name}" for name in dict.fromkeys(wanted) if name and name not in available]
            return missing + self._missing_models(client, requires.get("models") or {})

    def list_models(self) -> list[str]:
        try:
            with self._client() as client:
                return sorted(self._listing(client, "/models/checkpoints") or [])
        except (TransientError, ProviderError):
            return []

    def estimate(self, request: dict) -> list[Usage]:
        options = (request.get("template") or {}).get("options") or {}
        seconds = options.get("expected_seconds") or int(request.get("duration") or 5) * 60
        return [Usage("gpu_second", float(seconds))]
