"""Provider adapter contract.

The engine never talks to a vendor directly. Each provider instance (a row in provider_instances)
is served by one adapter chosen by its protocol. Requests are normalized per kind:

- llm:   {"system": str, "messages": [{"role": "user"|"assistant", "content": str}],
          "schema": dict, "schema_name": str, "temperature": float|None, "max_tokens": int|None,
          "seed": int|None}
         → Outcome.data = {"json": <parsed object>, "raw": <provider text or tool input>, "model": str}
- image: {"prompt": str, "references": [Path], "n": int, "size": str|None, "params": dict}
         → Outcome.files = images
- video: {"prompt": str, "references": [{"path": Path, "role": str}], "duration": int,
          "resolution": str, "template": dict|None, "seed": int|None, "params": dict}
         → Outcome.files = [video]
- tts:   {"text": str, "voice": dict, "speaker": Path|None} → Outcome.files = [audio]
- music: {"prompt": str, "lyrics": str, "duration": int|None} → Outcome.files = [audio]

Synchronous adapters implement run(). Asynchronous adapters implement submit()/poll() and keep the
engine's GPU or quota slot occupied while the upstream job runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class Instance:
    name: str
    kind: str
    protocol: str
    base_url: str = ""
    secret: str = ""
    model: str = ""
    pool: str = ""
    capabilities: dict = field(default_factory=dict)
    retry_safe: bool = True
    max_attempts: int = 3
    timeout_seconds: int = 1800
    pricing: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)


@dataclass
class Usage:
    unit: str          # token_in | token_out | image | video_second | audio_second | gpu_second | call
    quantity: float


@dataclass
class OutputFile:
    path: Path
    mime: str
    label: str = ""


@dataclass
class Outcome:
    files: list[OutputFile] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    usage: list[Usage] = field(default_factory=list)


@dataclass
class Progress:
    fraction: float | None = None
    message: str = ""


@dataclass
class TaskContext:
    task_id: str
    workdir: Path
    heartbeat: Callable[[], None] = lambda: None
    cancel_requested: Callable[[], bool] = lambda: False
    log: Callable[[str], None] = lambda message: None


class ProviderError(RuntimeError):
    """The provider answered and said no (bad request, failed job, content rejected)."""


class InputError(ProviderError):
    """Our own request is wrong (missing file, compose warning, bad template). Retrying cannot help."""


class TransientError(RuntimeError):
    """Network blip or 5xx while polling. The engine retries the same step later; state is unchanged."""


class SubmissionUnknown(RuntimeError):
    """We sent a submission but cannot tell whether it was accepted. Never resubmit blindly."""


class Adapter:
    kind: str = ""
    protocol: str = ""
    sync: bool = True
    poll_interval: float = 15.0

    def __init__(self, instance: Instance):
        self.instance = instance

    def run(self, request: dict, ctx: TaskContext) -> Outcome:
        raise NotImplementedError

    def submit(self, request: dict, ctx: TaskContext) -> dict:
        raise NotImplementedError

    def poll(self, ref: dict, ctx: TaskContext) -> Progress | Outcome:
        raise NotImplementedError

    def cancel(self, ref: dict, ctx: TaskContext) -> bool:
        """Return True if the upstream job was stopped. False means it will finish (and bill) anyway."""
        return False

    def find(self, ctx: TaskContext) -> dict | None:
        """After a crash during submission: look the job up by our task id. None if not found or unsupported."""
        return None

    def estimate(self, request: dict) -> list[Usage]:
        return [Usage("call", 1)]

    def probe(self) -> dict:
        return {"reachable": True, "message": "未检测"}

    def list_models(self) -> list[str]:
        return []

    def check_template(self, template: dict) -> list[str]:
        """Return missing requirements for a ComfyUI-style template on this instance."""
        return []


def http_options(instance: Instance) -> dict:
    """Proxy policy per instance (options.proxy): "env" follows HTTP(S)_PROXY / NO_PROXY (default for
    external APIs), "none" connects directly (default for ComfyUI hosts on the LAN), anything else is
    used as the proxy URL."""
    default = "none" if instance.protocol == "comfyui" else "env"
    proxy = (instance.options or {}).get("proxy", default)
    if proxy == "none":
        return {"trust_env": False}
    if proxy and proxy != "env":
        return {"trust_env": False, "proxy": proxy}
    return {"trust_env": True}


def cost_of(usage: list[Usage], pricing: dict) -> float:
    return round(sum(float(pricing.get(item.unit, 0)) * float(item.quantity) for item in usage), 4)
