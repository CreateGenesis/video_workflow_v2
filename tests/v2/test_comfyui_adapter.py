"""ComfyUI adapter against a small stateful fake of the ComfyUI HTTP API (no network, no database)."""

from __future__ import annotations

import copy
import email.policy
import json
import socket
import threading
import time
import uuid
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from server.providers.base import (
    Instance, Outcome, Progress, ProviderError, SubmissionUnknown, TaskContext, TransientError, Usage,
)
from server.providers.comfyui import ComfyUIAdapter, prompt_id_for

VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42fake-video"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png"
FINAL = {"done", "error", "interrupted"}


class FakeComfy:
    """Just enough ComfyUI: uploads, /prompt validation, queue -> running -> history, /view, cancel, info."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.url = ""
        self.mode = ""              # node_errors_partial | exec_error | drop_prompt | upload_fail
        self.supports_prompt_id = True
        self.auto_advance = True    # each repeated GET /history/<id> moves a job one stage on
        self.number = 10
        self.uploads: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.foreign_pending: list[list] = []
        self.files: dict[tuple[str, str, str], bytes] = {}
        self.prompts: list[dict] = []
        self.interrupts: list[dict] = []
        self.queue_deletes: list[str] = []
        self.auth: list[str | None] = []
        self.node_classes = {"KSampler", "CheckpointLoaderSimple", "CLIPTextEncode", "LoadImage",
                             "WanImageToVideo", "SaveVideo"}
        self.models = {"checkpoints": ["wan.safetensors", "sd15/base.safetensors"], "loras": ["lora_a.safetensors"]}

    # -- state ---------------------------------------------------------------------------------

    def item(self, job: dict) -> list:
        return [job["number"], job["id"], job["prompt"], job["extra"], ["9"]]

    def advance(self, job: dict) -> None:
        if job["stage"] == "pending":
            job["stage"] = "running"
        elif job["stage"] == "running":
            self.finish(job, "error" if self.mode == "exec_error" else "done")

    def finish(self, job: dict, stage: str) -> None:
        job["stage"] = stage
        if stage == "done":
            name = f"cvgen_{job['number']:05d}_.mp4"
            self.files[("video", name, "output")] = VIDEO_BYTES
            job["outputs"] = {"9": {"images": [{"filename": name, "subfolder": "video", "type": "output"}],
                                    "animated": [True]}}

    def history_entry(self, job: dict) -> dict:
        messages = [["execution_start", {"prompt_id": job["id"], "timestamp": 1}]]
        if job["stage"] == "done":
            status = {"status_str": "success", "completed": True,
                      "messages": messages + [["execution_success", {"prompt_id": job["id"]}]]}
        elif job["stage"] == "error":
            status = {"status_str": "error", "completed": False, "messages": messages + [["execution_error", {
                "prompt_id": job["id"], "node_id": "3", "node_type": "KSampler",
                "exception_message": "CUDA out of memory", "exception_type": "torch.OutOfMemoryError"}]]}
        else:
            status = {"status_str": "error", "completed": False,
                      "messages": messages + [["execution_interrupted", {"prompt_id": job["id"], "node_id": "3"}]]}
        return {"prompt": self.item(job), "outputs": job.get("outputs", {}), "status": status, "meta": {}}

    def validate(self, graph: dict) -> dict:
        errors = {}
        for node_id, node in graph.items():
            problem = ""
            if node["class_type"] not in self.node_classes:
                problem = f"Node '{node['class_type']}' not found"
            elif node["class_type"] == "LoadImage" and node["inputs"]["image"] not in self.uploads:
                problem = f"Invalid image file: {node['inputs']['image']}"
            if problem:
                errors[node_id] = {"errors": [{"type": "invalid", "message": problem, "details": ""}],
                                   "dependent_outputs": ["9"], "class_type": node["class_type"]}
        return errors

    # -- routes ---------------------------------------------------------------------------------

    def get(self, path: str, query: dict) -> tuple[int, object]:
        if path.startswith("/history/"):
            job = self.jobs.get(path.removeprefix("/history/"))
            if job is None:
                return 200, {}
            if self.auto_advance and job.get("seen"):
                self.advance(job)
            job["seen"] = True
            return 200, ({job["id"]: self.history_entry(job)} if job["stage"] in FINAL else {})
        if path == "/history":
            done = [self.history_entry(job) for job in self.jobs.values() if job["stage"] in FINAL]
            limit = int(query.get("max_items", ["1000"])[0])
            return 200, {entry["prompt"][1]: entry for entry in done[-limit:]}
        if path == "/queue":
            running = [self.item(job) for job in self.jobs.values() if job["stage"] == "running"]
            pending = [self.item(job) for job in self.jobs.values() if job["stage"] == "pending"]
            return 200, {"queue_running": running, "queue_pending": pending + self.foreign_pending}
        if path == "/system_stats":
            return 200, {"system": {"os": "posix", "comfyui_version": "0.3.60"}, "devices": [
                {"name": "cuda:0 NVIDIA GeForce RTX 4090", "type": "cuda", "index": 0,
                 "vram_total": 25393692672, "vram_free": 24000000000}]}
        if path == "/object_info":
            return 200, {name: {"name": name, "input": {}, "output": []} for name in self.node_classes}
        if path == "/models":
            return 200, list(self.models)
        if path.startswith("/models/") and path.removeprefix("/models/") in self.models:
            return 200, self.models[path.removeprefix("/models/")]
        return 404, {"error": "not found"}

    def post(self, path: str, body: dict) -> tuple[int, object]:
        if path == "/prompt":
            return self.post_prompt(body)
        if path == "/queue":
            for prompt_id in body.get("delete", []):
                self.queue_deletes.append(prompt_id)
                if self.jobs.get(prompt_id, {}).get("stage") == "pending":
                    del self.jobs[prompt_id]
            return 200, None
        if path == "/history":
            for prompt_id in body.get("delete", []):
                if self.jobs.get(prompt_id, {}).get("stage") in FINAL:
                    del self.jobs[prompt_id]
            return 200, None
        if path == "/interrupt":
            self.interrupts.append(body)
            for job in self.jobs.values():
                if job["stage"] == "running" and body.get("prompt_id") in (None, job["id"]):
                    self.finish(job, "interrupted")
            return 200, None
        return 404, {"error": "not found"}

    def post_prompt(self, body: dict) -> tuple[int, object]:
        self.prompts.append(body)
        errors = self.validate(body["prompt"])
        if errors and self.mode != "node_errors_partial":
            return 400, {"error": {"type": "prompt_outputs_failed_validation",
                                   "message": "Prompt outputs failed validation", "details": ""},
                         "node_errors": errors}
        prompt_id = body.get("prompt_id") if self.supports_prompt_id else str(uuid.uuid4())
        extra = {**body.get("extra_data", {}), "client_id": body.get("client_id"), "create_time": 1}
        self.jobs[prompt_id] = {"id": prompt_id, "number": self.number, "prompt": body["prompt"],
                                "extra": extra, "stage": "pending"}
        self.number += 1
        if self.mode == "drop_prompt":
            return 0, None
        return 200, {"prompt_id": prompt_id, "number": self.number - 1, "node_errors": errors}

    def upload(self, fields: dict, files: dict) -> tuple[int, object]:
        if self.mode == "upload_fail":
            return 500, {"error": "disk full"}
        filename, data = files["image"]
        self.uploads[filename] = {"bytes": data, **fields}
        return 200, {"name": filename, "subfolder": "", "type": "input"}


def _multipart(content_type: str, body: bytes) -> tuple[dict, dict]:
    message = BytesParser(policy=email.policy.default).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body)
    fields, files = {}, {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if part.get_filename():
            files[name] = (part.get_filename(), part.get_payload(decode=True))
        else:
            fields[name] = part.get_content().strip()
    return fields, files


def _handler(fake: FakeComfy) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _reply(self, status: int, payload: object, raw: bytes | None = None) -> None:
            if status == 0:  # drop the connection without answering
                self.close_connection = True
                return
            data = raw if raw is not None else json.dumps(payload).encode() if payload is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream" if raw is not None else "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            query = parse_qs(url.query, keep_blank_values=True)
            with fake.lock:
                fake.auth.append(self.headers.get("Authorization"))
                if url.path == "/view":
                    key = (query["subfolder"][0], query["filename"][0], query["type"][0])
                    data = fake.files.get(key)
                    return self._reply(200, None, data) if data is not None else self._reply(404, {})
                self._reply(*fake.get(url.path, query))

        def do_POST(self) -> None:
            url = urlsplit(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            with fake.lock:
                fake.auth.append(self.headers.get("Authorization"))
                if url.path == "/upload/image":
                    return self._reply(*fake.upload(*_multipart(self.headers["Content-Type"], body)))
                self._reply(*fake.post(url.path, json.loads(body or b"{}")))

    return Handler


@pytest.fixture
def fake():
    state = FakeComfy()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


def _closed_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


def _adapter(url: str, secret: str = "") -> ComfyUIAdapter:
    return ComfyUIAdapter(Instance(name="gpu1", kind="video", protocol="comfyui", base_url=url, secret=secret))


def _template() -> dict:
    return {
        "graph": {
            "3": {"class_type": "KSampler", "inputs": {"seed": 0, "steps": 20, "cfg": 6.0, "model": ["4", 0]}},
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "wan.safetensors"}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder", "clip": ["4", 1]}},
            "12": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
            "13": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
            "20": {"class_type": "WanImageToVideo", "inputs": {
                "width": 832, "height": 480, "length": 33, "start_image": ["12", 0], "end_image": ["13", 0]}},
            "9": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "cvgen", "fps": 24, "video": ["20", 0]}},
        },
        "bindings": {"prompt": "6.inputs.text", "image": "12.inputs.image", "image_1": "13.inputs.image",
                     "seed": "3.inputs.seed", "length": "20.inputs.length", "width": "20.inputs.width",
                     "height": "20.inputs.height", "fps": "9.inputs.fps", "steps": "3.inputs.steps"},
        "outputs": ["9"],
        "requires": {"nodes": ["WanImageToVideo"], "models": {"checkpoints": ["wan.safetensors"]}},
        "options": {"fps": 16, "length_plus_one": True, "expected_seconds": 600},
    }


def _text_template() -> dict:
    template = _template()
    for node_id in ("12", "13"):
        del template["graph"][node_id]
    del template["graph"]["20"]["inputs"]["start_image"], template["graph"]["20"]["inputs"]["end_image"]
    del template["bindings"]["image"], template["bindings"]["image_1"]
    return template


def _request(tmp_path: Path, **overrides) -> dict:
    first, last = tmp_path / "first.png", tmp_path / "last.jpg"
    first.write_bytes(PNG_BYTES)
    last.write_bytes(b"\xff\xd8fake-jpeg")
    request = {
        "prompt": "一只猫在雨里跳舞",
        "references": [{"path": first, "role": "首帧"}, {"path": last, "role": "尾帧"}],
        "duration": 5, "resolution": "480p竖", "template": _template(), "seed": 1234,
        "params": {"steps": 8, "no_such_binding": 1, "seed": 99},
    }
    return {**request, **overrides}


def _ctx(tmp_path: Path, task_id: str = "task-1", log: list | None = None) -> TaskContext:
    return TaskContext(task_id=task_id, workdir=tmp_path / "work",
                       log=(log.append if log is not None else lambda message: None))


def _poll_until_done(adapter: ComfyUIAdapter, ref: dict, ctx: TaskContext, limit: int = 6) -> tuple[list, Outcome]:
    seen = []
    for _ in range(limit):
        result = adapter.poll(ref, ctx)
        if isinstance(result, Outcome):
            return seen, result
        seen.append(result.message)
    raise AssertionError(f"never finished: {seen}")


# -- submission ---------------------------------------------------------------------------------

def test_submit_uploads_references_and_fills_every_binding(fake, tmp_path):
    request = _request(tmp_path)
    original = copy.deepcopy(request["template"])
    ref = _adapter(fake.url).submit(request, _ctx(tmp_path))

    ours = prompt_id_for("task-1")
    assert ref["prompt_id"] == ours and fake.prompts[0]["prompt_id"] == ours
    assert ref["client_id"] == "cvgen-gpu1" == fake.prompts[0]["client_id"]
    assert ref["seed"] == 1234 and ref["outputs"] == ["9"] and ref["submitted_at"] <= time.time()
    assert fake.prompts[0]["extra_data"]["cvgen_task"] == "task-1"

    assert set(fake.uploads) == {"task-1-0.png", "task-1-1.jpg"}
    assert fake.uploads["task-1-0.png"]["bytes"] == PNG_BYTES
    assert fake.uploads["task-1-0.png"]["overwrite"] == "true"

    graph = fake.jobs[ours]["prompt"]
    assert graph["6"]["inputs"]["text"] == "一只猫在雨里跳舞"
    assert graph["12"]["inputs"]["image"] == "task-1-0.png"
    assert graph["13"]["inputs"]["image"] == "task-1-1.jpg"
    assert graph["3"]["inputs"]["seed"] == 1234          # params cannot override the request seed
    assert graph["3"]["inputs"]["steps"] == 8            # params with a binding are applied
    assert graph["3"]["inputs"]["cfg"] == 6.0            # unbound inputs are left alone
    assert graph["20"]["inputs"]["length"] == 5 * 16 + 1
    assert (graph["20"]["inputs"]["width"], graph["20"]["inputs"]["height"]) == (480, 854)
    assert graph["9"]["inputs"]["fps"] == 16
    assert "no_such_binding" not in json.dumps(graph)
    assert request["template"] == original               # the library asset is never mutated


def test_random_seed_is_recorded_and_plain_path_references_work(fake, tmp_path):
    request = _request(tmp_path, seed=None, params={})
    request["references"] = [item["path"] for item in request["references"]]   # image-kind shape
    ref = _adapter(fake.url).submit(request, _ctx(tmp_path))
    assert isinstance(ref["seed"], int)
    assert fake.jobs[ref["prompt_id"]]["prompt"]["3"]["inputs"]["seed"] == ref["seed"]
    assert fake.jobs[ref["prompt_id"]]["prompt"]["3"]["inputs"]["steps"] == 20


def test_broken_bindings_and_missing_references_fail_before_uploading(fake, tmp_path):
    adapter = _adapter(fake.url)
    for path in ("99.inputs.text", "6.inputs.txt", "6.text"):
        template = _template()
        template["bindings"]["prompt"] = path
        with pytest.raises(ProviderError, match="找不到"):
            adapter.submit(_request(tmp_path, template=template), _ctx(tmp_path))
    with pytest.raises(ProviderError, match="2 张参考图"):
        request = _request(tmp_path)
        adapter.submit({**request, "references": request["references"][:1]}, _ctx(tmp_path))
    with pytest.raises(ProviderError, match="分辨率"):
        adapter.submit(_request(tmp_path, resolution="1080p"), _ctx(tmp_path))
    assert fake.uploads == {} and fake.prompts == []


def test_node_errors_are_a_provider_error(fake, tmp_path):
    template = _text_template()
    template["graph"]["9"]["class_type"] = "VHS_VideoCombine"
    with pytest.raises(ProviderError) as caught:
        _adapter(fake.url).submit(_request(tmp_path, template=template, references=[]), _ctx(tmp_path))
    assert "VHS_VideoCombine" in str(caught.value) and "节点 9" in str(caught.value)
    assert fake.jobs == {}


def test_partly_valid_graph_is_taken_back_out_of_the_queue(fake, tmp_path):
    fake.mode = "node_errors_partial"
    template = _text_template()
    template["graph"]["9"]["class_type"] = "VHS_VideoCombine"
    with pytest.raises(ProviderError):
        _adapter(fake.url).submit(_request(tmp_path, template=template, references=[]), _ctx(tmp_path))
    assert fake.queue_deletes == [prompt_id_for("task-1")] and fake.jobs == {}


def test_upload_failure_is_transient_and_submits_nothing(fake, tmp_path):
    fake.mode = "upload_fail"
    with pytest.raises(TransientError):
        _adapter(fake.url).submit(_request(tmp_path), _ctx(tmp_path))
    assert fake.prompts == []


def test_network_failure_on_prompt_is_submission_unknown(tmp_path):
    request = _request(tmp_path, template=_text_template(), references=[])
    with pytest.raises(SubmissionUnknown):
        _adapter(_closed_url()).submit(request, _ctx(tmp_path))


def test_dropped_submission_is_found_again_after_a_crash(fake, tmp_path):
    fake.mode = "drop_prompt"
    adapter = _adapter(fake.url)
    with pytest.raises(SubmissionUnknown):
        adapter.submit(_request(tmp_path, template=_text_template(), references=[]), _ctx(tmp_path))
    found = adapter.find(_ctx(tmp_path))
    assert found["prompt_id"] == prompt_id_for("task-1")
    assert found["seed"] == 1234 and found["outputs"] == ["9"] and found["client_id"] == "cvgen-gpu1"
    assert adapter.find(_ctx(tmp_path, task_id="never-submitted")) is None

    fake.mode = ""
    _, outcome = _poll_until_done(adapter, found, _ctx(tmp_path))
    assert outcome.files[0].path.read_bytes() == VIDEO_BYTES


# -- polling ------------------------------------------------------------------------------------

def test_poll_moves_from_queue_to_running_to_downloaded_outcome(fake, tmp_path):
    adapter = _adapter(fake.url)
    ref = adapter.submit(_request(tmp_path), _ctx(tmp_path))
    fake.foreign_pending.append([3, "someone-else", {}, {}, []])   # earlier number, listed later: heap order

    messages, outcome = _poll_until_done(adapter, ref, _ctx(tmp_path))
    assert messages == ["排队第 2 位", "渲染中"]
    [output] = outcome.files
    assert output.path == tmp_path / "work" / "9-cvgen_00010_.mp4"
    assert output.path.read_bytes() == VIDEO_BYTES and output.mime == "video/mp4"
    assert not list((tmp_path / "work").glob("*.partial"))
    [usage] = outcome.usage
    assert usage.unit == "gpu_second" and usage.quantity >= 0


def test_server_that_ignores_client_prompt_id(fake, tmp_path):
    fake.supports_prompt_id = False
    adapter, log = _adapter(fake.url), []
    ref = adapter.submit(_request(tmp_path), _ctx(tmp_path, log=log))
    assert ref["prompt_id"] != prompt_id_for("task-1") and ref["prompt_id"] in fake.jobs
    assert log and "prompt_id" in log[0]
    _poll_until_done(adapter, ref, _ctx(tmp_path))
    assert adapter.find(_ctx(tmp_path))["prompt_id"] == ref["prompt_id"]   # found by extra_data in history


def test_execution_error_in_history_is_a_provider_error(fake, tmp_path):
    fake.mode = "exec_error"
    adapter = _adapter(fake.url)
    ref = adapter.submit(_request(tmp_path), _ctx(tmp_path))
    with pytest.raises(ProviderError, match="CUDA out of memory"):
        _poll_until_done(adapter, ref, _ctx(tmp_path))


def test_retry_after_failure_does_not_read_the_old_history(fake, tmp_path):
    fake.mode = "exec_error"
    adapter = _adapter(fake.url)
    ref = adapter.submit(_request(tmp_path), _ctx(tmp_path))
    with pytest.raises(ProviderError):
        _poll_until_done(adapter, ref, _ctx(tmp_path))
    fake.mode = ""
    retry = adapter.submit(_request(tmp_path), _ctx(tmp_path))
    assert retry["prompt_id"] == ref["prompt_id"]
    assert isinstance(adapter.poll(retry, _ctx(tmp_path)), Progress)


def test_job_missing_everywhere_is_transient(fake, tmp_path):
    ref = {"prompt_id": "gone", "submitted_at": time.time(), "outputs": ["9"]}
    with pytest.raises(TransientError, match="不在队列也不在历史"):
        _adapter(fake.url).poll(ref, _ctx(tmp_path))
    with pytest.raises(TransientError):
        _adapter(_closed_url()).poll(ref, _ctx(tmp_path))


# -- cancel -------------------------------------------------------------------------------------

def test_cancel_pending_running_and_finished(fake, tmp_path):
    fake.auto_advance = False
    adapter = _adapter(fake.url)

    pending = adapter.submit(_request(tmp_path), _ctx(tmp_path, "task-a"))
    assert adapter.cancel(pending, _ctx(tmp_path)) is True
    assert fake.queue_deletes == [pending["prompt_id"]] and pending["prompt_id"] not in fake.jobs

    running = adapter.submit(_request(tmp_path), _ctx(tmp_path, "task-b"))
    fake.jobs[running["prompt_id"]]["stage"] = "running"
    assert adapter.cancel(running, _ctx(tmp_path)) is True
    assert fake.interrupts == [{"prompt_id": running["prompt_id"]}]
    with pytest.raises(ProviderError, match="中断"):
        adapter.poll(running, _ctx(tmp_path))

    finished = adapter.submit(_request(tmp_path), _ctx(tmp_path, "task-c"))
    fake.finish(fake.jobs[finished["prompt_id"]], "done")
    assert adapter.cancel(finished, _ctx(tmp_path)) is False


# -- environment --------------------------------------------------------------------------------

def test_check_template_reports_missing_nodes_and_models(fake):
    adapter = _adapter(fake.url)
    assert adapter.check_template(_template()) == []

    template = _template()
    template["graph"]["9"]["class_type"] = "VHS_VideoCombine"
    template["requires"] = {"nodes": ["WanImageToVideo", "WanVideoSampler"], "models": {
        "checkpoints": ["wan.safetensors", "missing.safetensors"], "unet": ["only-on-new-comfy.gguf"]}}
    assert adapter.check_template(template) == [
        "缺少节点 WanVideoSampler", "缺少节点 VHS_VideoCombine", "缺少模型 checkpoints/missing.safetensors"]

    template["requires"] = {"models": ["sd15/base.safetensors", "lora_a.safetensors", "nope.safetensors"]}
    assert adapter.check_template(template) == ["缺少节点 VHS_VideoCombine", "缺少模型 nope.safetensors"]


def test_probe_models_estimate_and_bearer_token(fake, tmp_path):
    adapter = _adapter(fake.url, secret="tok")
    probe = adapter.probe()
    assert probe["reachable"] is True and "0.3.60" in probe["message"]
    assert probe["devices"][0]["type"] == "cuda" and isinstance(probe["latency_ms"], int)
    assert adapter.list_models() == ["sd15/base.safetensors", "wan.safetensors"]
    assert set(fake.auth) == {"Bearer tok"}

    fake.auth.clear()
    _adapter(fake.url).probe()
    assert fake.auth == [None]

    closed = _adapter(_closed_url())
    assert closed.probe()["reachable"] is False and closed.probe()["devices"] == []
    assert closed.list_models() == []

    assert adapter.estimate(_request(tmp_path)) == [Usage("gpu_second", 600.0)]
    assert adapter.estimate({"duration": 4, "template": _text_template() | {"options": {}}}) == [Usage("gpu_second", 240.0)]
