"""Protocol registry. A provider instance's protocol picks the adapter class."""

from __future__ import annotations

import importlib

from .base import Adapter, Instance

PROTOCOLS: dict[str, tuple[str, str, set[str]]] = {
    "mock": ("server.providers.mock", "MockAdapter", {"llm", "image", "video", "tts", "music"}),
    "openai-chat": ("server.providers.llm", "OpenAIChatAdapter", {"llm"}),
    "openai-responses": ("server.providers.llm", "OpenAIResponsesAdapter", {"llm"}),
    "anthropic-messages": ("server.providers.llm", "AnthropicMessagesAdapter", {"llm"}),
    "openai-images": ("server.providers.openai_media", "OpenAIImageAdapter", {"image"}),
    "openai-audio": ("server.providers.openai_media", "OpenAIAudioAdapter", {"music", "tts"}),
    "autodl-h3": ("server.providers.autodl", "AutoDLH3Adapter", {"video"}),
    "autodl-indextts": ("server.providers.autodl", "AutoDLIndexTTSAdapter", {"tts"}),
    "comfyui": ("server.providers.comfyui", "ComfyUIAdapter", {"video", "image", "tts", "music"}),
}
KINDS = ("llm", "image", "video", "tts", "music")


def protocol_kinds(protocol: str) -> set[str]:
    if protocol not in PROTOCOLS:
        raise ValueError(f"没有这个协议：{protocol}")
    return PROTOCOLS[protocol][2]


def adapter_for(instance: Instance) -> Adapter:
    module_name, class_name, kinds = PROTOCOLS[instance.protocol]
    if instance.kind not in kinds:
        raise ValueError(f"协议 {instance.protocol} 不能用于 {instance.kind}")
    adapter_class = getattr(importlib.import_module(module_name), class_name)
    adapter = adapter_class(instance)
    adapter.kind = instance.kind
    return adapter
