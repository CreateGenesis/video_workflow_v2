"""Hosted jobs. cvgen starts them; this module finishes them."""

from __future__ import annotations

import threading
import urllib.request
from pathlib import Path

from .compose import compose
from .media import contact_sheet, frame_at, loudness, probe
from .rules import passthrough_allowed, provider_outcome
from .store import Store


class JobRunner:
    def __init__(self, store: Store, storage, public_base: str, data: Path):
        self.store = store
        self.storage = storage
        self.public_base = public_base
        self.data = data

    def start(self, kind: str, target_id: str | None, detail: dict) -> dict:
        if kind == "generate" and target_id:
            job = self.store.claim_generate(target_id, detail)
        else:
            job = self.store.add_job(kind, target_id, "queued", detail)
        thread = threading.Thread(target=self._run, args=(job["id"],), daemon=True)
        thread.start()
        return {"job_id": job["id"], "status": "queued", "kind": kind}

    def resume_open(self) -> list[str]:
        resumed = []
        for job in self.store.list_jobs():
            if job["status"] not in {"queued", "running"}:
                continue
            if job["kind"] == "generate" and not (job["detail"] or {}).get("submitted"):
                continue
            threading.Thread(target=self._run, args=(job["id"],), name=f"cvgen-{job['id']}", daemon=True).start()
            resumed.append(job["id"])
        return resumed

    def _run(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        self.store.update_job(job_id, "running", job["detail"])
        try:
            handler = {
                "generate": self._generate,
                "tts": self._tts,
                "pull": self._pull,
                "inspect": self._inspect,
                "reverse": self._reverse,
                "learn": self._learn,
                "style": self._style,
                "edit": self._edit,
                "ffmpeg": self._ffmpeg,
                "image": self._image,
                "music": self._music,
                "check": self._check,
                "frame": self._frame,
            }[job["kind"]]
            detail = handler(job)
            self.store.update_job(job_id, "succeeded", detail)
        except Exception as exc:
            current = self.store.get_job(job_id)
            detail = dict(current["detail"])
            detail["error"] = str(exc)
            status = "unknown" if detail.get("submitted") or "不明" in str(exc) else "failed"
            self.store.update_job(job_id, status, detail)

    def _generate(self, job: dict) -> dict:
        from h3_client import build_body, download, query, submit

        detail = dict(job["detail"])
        if detail.get("submitted") and detail.get("provider_task"):
            state = self._wait_provider(query, detail["provider_task"])
            plan = compose(self.store, job["target_id"], detail.get("resolution") or "768p横")
            return self._store_generated(job, detail, state, plan["resolution"], plan["duration"], plan["prompt"])
        plan = compose(self.store, job["target_id"], detail.get("resolution") or "768p横")
        if plan["warnings"] and not detail.get("force"):
            raise RuntimeError("组合有警告：" + "；".join(plan["warnings"]))
        if not plan["references"]:
            raise RuntimeError("没有参考图，不能提交")
        images = []
        asset_root = Path(__file__).resolve().parents[1] / "assets"
        for ref in plan["references"]:
            if not ref.get("object_key"):
                raise RuntimeError(f"参考 {ref['title']} 还没有文件")
            suffix = Path(ref["object_key"]).suffix or ".png"
            path = self.data / "tmp" / f"{ref['id']}{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                payload = self.storage.get(ref["object_key"])
            except Exception:
                bundled = asset_root / ref["object_key"]
                if not bundled.is_file():
                    raise
                payload = bundled.read_bytes()
                self.storage.put(ref["object_key"].split("/", 1)[0], ref["object_key"].split("/", 1)[1], payload, "image/png")
            path.write_bytes(payload)
            images.append(str(path))
        body = build_body(plan["prompt"], images, duration=plan["duration"], resolution=plan["resolution"])
        try:
            accepted = submit(body)
        except Exception as exc:
            raise RuntimeError(f"提交不明，不自动重发：{exc}") from exc
        detail["provider_task"] = accepted["task_id"]
        detail["submitted"] = True
        detail["prompt"] = plan["prompt"]
        self.store.update_job(job["id"], "running", detail)
        state = self._wait_provider(query, accepted["task_id"])
        return self._store_generated(job, detail, state, plan["resolution"], plan["duration"], plan["prompt"])

    def _store_generated(self, job: dict, detail: dict, state: dict, resolution: str, duration: int | None = None, prompt: str = "") -> dict:
        from h3_client import download

        if not state.get("video_url"):
            raise RuntimeError(state.get("msg") or "生成没有返回视频")
        local = self.data / "tmp" / f"{job['id']}.mp4"
        local.parent.mkdir(parents=True, exist_ok=True)
        download(state["video_url"], local)
        key = self.storage.put("clips", f"{job['id']}.mp4", local.read_bytes(), "video/mp4")
        clip = self.store.add_entity("Clip", {
            "title": job["target_id"],
            "duration": 0,
            "resolution": resolution,
        }, key)
        self._sheets(local, clip["id"], detail)
        detail["object_key"] = key
        detail["clip_id"] = clip["id"]
        return self._apply_record(job, detail, resolution, duration, prompt, clip["id"])

    def reconcile_stored(self, job_id: str) -> dict:
        job = self.store.get_job(job_id)
        if job["kind"] != "generate" or not job["detail"].get("object_key"):
            raise RuntimeError("只能核对已入库的生成")
        detail = dict(job["detail"])
        local = self.data / "tmp" / f"{job_id}-reconcile.mp4"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(self.storage.get(detail["object_key"]))
        anchor = detail.get("clip_id") or job_id
        self._sheets(local, anchor, detail)
        plan = compose(self.store, job["target_id"], detail.get("resolution") or "768p横")
        detail = self._apply_record(
            job, detail, plan["resolution"], plan["duration"], plan["prompt"], detail.get("clip_id"),
        )
        self.store.update_job(job_id, job["status"], detail)
        return detail

    def _apply_record(self, job: dict, detail: dict, resolution: str, duration: int | None, prompt: str, clip_id: str | None) -> dict:
        measured = float((detail.get("probe") or {}).get("duration") or 0)
        planned = float(duration or 0)
        stored_duration = measured or planned
        if prompt:
            detail["prompt"] = prompt
        detail["duration"] = stored_duration
        detail["estimate_yuan"] = round(stored_duration * 0.5, 2)
        if clip_id:
            clip = self.store.get_entity(clip_id)
            data = dict(clip["data"])
            data["duration"] = stored_duration
            data["resolution"] = resolution
            self.store.update_entity(clip_id, data)
            detail["clip_id"] = clip_id
        return detail

    def _voice_for(self, line_id: str) -> tuple[dict, dict]:
        incoming = [
            link for link in self.store.all_links()
            if link["name"] == "voices" and link["target_id"] == line_id
        ]
        if not incoming:
            raise RuntimeError("旁白没有连到音色")
        shot = self.store.get_entity(incoming[0]["source_id"])
        voice_links = self.store.links(shot["id"], "voiced_by")
        if not voice_links:
            raise RuntimeError("旁白没有连到音色")
        voice = self.store.get_entity(voice_links[0]["target_id"])
        refs = [self.store.get_entity(link["target_id"]) for link in self.store.links(voice["id"], "references")]
        speaker = next((item for item in refs if item["data"].get("role") == "音色"), None)
        if not speaker or not speaker.get("object_key"):
            raise RuntimeError("缺少音色参考音频")
        return voice, speaker

    def _tts(self, job: dict) -> dict:
        from h3_client import config, download, query, _request

        line = self.store.get_entity(job["target_id"])
        voice, speaker = self._voice_for(job["target_id"])
        cfg = config()
        audio = self.storage.get(speaker["object_key"])
        import base64
        mime = "audio/wav" if speaker["object_key"].endswith(".wav") else "audio/mpeg"
        body = {
            "prompt_text": line["data"].get("text"),
            "prompt_simple": f"data:{mime};base64,{base64.b64encode(audio).decode('ascii')}",
            "emo_control_method": voice["data"].get("method") or "与音色参考音频相同",
        }
        for name in ("happy", "angry", "sad", "afraid", "disgusted", "melancholic", "surprised", "calm"):
            if voice["data"].get(name) not in (None, ""):
                body[f"emo_{name}"] = float(voice["data"][name])
        status, payload = _request(
            f"{cfg['base']}/api/v1/comfyui/comfyui_workflow/indextts2-v1",
            cfg["token"],
            body,
        )
        if status != 200 or not (payload.get("data") or {}).get("task_id"):
            raise RuntimeError(f"配音提交不明，不自动重发：{payload.get('msg')}")
        detail = dict(job["detail"])
        detail["submitted"] = True
        detail["provider_task"] = payload["data"]["task_id"]
        self.store.update_job(job["id"], "running", detail)
        state = self._wait_provider(query, payload["data"]["task_id"])
        audio_url = state.get("video_url")
        if not audio_url:
            raise RuntimeError(state.get("msg") or "配音没有返回文件")

        local = self.data / "tmp" / f"{job['id']}.wav"
        local.parent.mkdir(parents=True, exist_ok=True)
        download(audio_url, local)
        key = self.storage.put("clips", f"{job['id']}.wav", local.read_bytes(), "audio/wav")
        clip = self.store.add_entity("Clip", {"title": line["data"].get("title") or "旁白"}, key)
        detail["clip_id"] = clip["id"]
        detail["object_key"] = key
        return detail

    def _wait_provider(self, query, task_id: str, limit: int = 1500) -> dict:
        import time

        started = time.time()
        while time.time() - started < limit:
            state = query(task_id)
            outcome = provider_outcome(state)
            if outcome == "ready":
                return state
            if outcome == "failed":
                raise RuntimeError(state.get("msg") or "供应商任务失败，不自动重发")
            if outcome == "unknown":
                raise RuntimeError("供应商状态不明，不自动重发")
            time.sleep(15)
        raise RuntimeError("仍在运行，任务保留，不自动重发")

    def _sheets(self, local: Path, clip_id: str, detail: dict) -> None:
        sheet = self.data / "tmp" / f"{clip_id}-sheet.jpg"
        last = self.data / "tmp" / f"{clip_id}-last.jpg"
        contact_sheet(local, sheet)
        info = probe(local)
        frame_at(local, last, max(0, info["duration"] - 0.1))
        detail["sheet_key"] = self.storage.put("previews", f"{clip_id}-sheet.jpg", sheet.read_bytes(), "image/jpeg")
        detail["last_key"] = self.storage.put("previews", f"{clip_id}-last.jpg", last.read_bytes(), "image/jpeg")
        detail["probe"] = info

    def _pull(self, job: dict) -> dict:
        url = job["detail"]["url"]
        req = urllib.request.Request(url, headers={"User-Agent": "cvgen"})
        with urllib.request.urlopen(req, timeout=120) as response:
            data = response.read()
            mime = response.headers.get_content_type()
        suffix = ".mp4" if "video" in mime else ".png"
        bucket = "clips" if "video" in mime else "references"
        key = self.storage.put(bucket, f"{job['id']}{suffix}", data, mime)
        entity = self.store.add_entity(
            "Reference",
            {"title": url[:80], "role": job["detail"].get("role") or "风格", "source_url": url},
            key,
        )
        detail = dict(job["detail"])
        detail.update({"entity_id": entity["id"], "object_key": key})
        return detail

    def _inspect(self, job: dict) -> dict:
        entity = self.store.get_entity(job["target_id"])
        if not entity.get("object_key"):
            raise RuntimeError("这个实体没有文件")
        local = self.data / "tmp" / Path(entity["object_key"]).name
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(self.storage.get(entity["object_key"]))
        info = probe(local)
        detail = dict(job["detail"])
        detail["probe"] = info
        if local.suffix.lower() in {".mp4", ".mov", ".webm"}:
            self._sheets(local, entity["id"], detail)
            detail["loudness"] = loudness(local)
        observation = self.store.add_entity("Observation", {"title": entity["id"], "summary": str(info)})
        detail["observed_id"] = entity["id"]
        detail["observation_id"] = observation["id"]
        return detail

    def _reverse(self, job: dict) -> dict:
        detail = self._inspect(job)
        probe_info = detail.get("probe") or {}
        draft = (
            f"这条片子约 {probe_info.get('duration')} 秒，画面 {probe_info.get('width')}x{probe_info.get('height')}。"
            "先按接触表复述镜头、动作和声音，确认后再写提示词。这里只保存草案，不提交生成。"
        )
        detail["draft"] = draft
        return detail

    def _learn(self, job: dict) -> dict:
        detail = self._pull(job)
        entity = self.store.get_entity(detail["entity_id"])
        observation = self.store.add_entity("Observation", {
            "title": entity["data"].get("title") or entity["id"],
            "summary": "服务已下载并入库。字幕和转写由服务侧继续补，agent 不自己下载。",
        })
        detail["learned_from"] = entity["id"]
        detail["observation_id"] = observation["id"]
        detail["note"] = observation["data"]["summary"]
        return detail

    def _style(self, job: dict) -> dict:
        detail = self._inspect(job)
        info = detail.get("probe") or {}
        style = self.store.add_entity("Style", {
            "title": f"提取自 {job['target_id']}",
            "medium": f"{info.get('width')}x{info.get('height')} {info.get('codec') or ''}",
            "grade": "从接触表和响度观察，由 agent 决定是否锁定",
            "ban": "禁止定格。",
        })
        detail["styled_from"] = job["target_id"]
        detail["style_id"] = style["id"]
        return detail

    def _require(self, capability: str) -> dict:
        from .providers import configured, resolve

        if not configured(self.store, capability):
            raise RuntimeError("这项能力还没有配置，不能提交")
        return resolve(self.store, capability)

    def _submit_hosted(self, capability: str, body: dict) -> tuple[dict, dict]:
        from h3_client import _request, download, query

        cfg = self._require(capability)
        url = f"{cfg['base'].rstrip('/')}/api/v1/comfyui/comfyui_workflow/{cfg['workflow']}"
        try:
            status, payload = _request(url, cfg["key"], body)
        except Exception as exc:
            raise RuntimeError(f"提交不明，不自动重发：{exc}") from exc
        data = payload.get("data") or {}
        if status != 200 or not data.get("task_id"):
            raise RuntimeError("提交没有被接受，不自动重发")
        state = self._wait_provider(query, data["task_id"])
        media_url = state.get("video_url")
        if not media_url:
            raise RuntimeError(state.get("msg") or "生成没有返回文件")
        return cfg, {"url": media_url, "download": download, "task_id": data["task_id"]}

    def _image(self, job: dict) -> dict:
        shot = self.store.get_entity(job["target_id"])
        if shot["type"] != "Shot":
            raise RuntimeError("只能为镜头生图")
        cfg, accepted = self._submit_hosted("image", {
            "prompt": shot["data"].get("action") or shot["data"].get("title") or "产品锚定图",
            "role": (job["detail"] or {}).get("role") or "细节",
        })
        local = self.data / "tmp" / f"{job['id']}.png"
        local.parent.mkdir(parents=True, exist_ok=True)
        accepted["download"](accepted["url"], local)
        role = (job["detail"] or {}).get("role") or "细节"
        key = self.storage.put("references", f"{job['id']}.png", local.read_bytes(), "image/png")
        entity = self.store.add_entity("Reference", {
            "title": shot["data"].get("title") or "生图参考",
            "role": role,
            "take": "只采用这张图里的产品和构图",
            "ignore": "不采用背景里无关的文字和标识",
        }, key)
        self.store.add_link("references", shot["id"], entity["id"], "生图入库")
        detail = dict(job["detail"])
        detail.update({"reference_id": entity["id"], "object_key": key, "workflow": cfg["workflow"]})
        return detail

    def _music(self, job: dict) -> dict:
        text = (job["detail"] or {}).get("text") or ""
        if not text.strip():
            target = self.store.get_entity(job["target_id"]) if job.get("target_id") else None
            text = (target or {}).get("data", {}).get("text") or (target or {}).get("data", {}).get("title") or ""
        if not text.strip():
            raise RuntimeError("没有台词或文本，不能生音乐")
        cfg, accepted = self._submit_hosted("music", {"prompt": text, "lyrics": text})
        local = self.data / "tmp" / f"{job['id']}.wav"
        local.parent.mkdir(parents=True, exist_ok=True)
        accepted["download"](accepted["url"], local)
        key = self.storage.put("clips", f"{job['id']}.wav", local.read_bytes(), "audio/wav")
        clip = self.store.add_entity("Clip", {"title": text[:40], "duration": 0}, key)
        detail = dict(job["detail"])
        detail.update({"clip_id": clip["id"], "object_key": key, "workflow": cfg["workflow"]})
        return detail

    def _check(self, job: dict) -> dict:
        from .rules import check_spec

        entity = self.store.get_entity(job["target_id"])
        if entity["type"] != "Clip" or not entity.get("object_key"):
            raise RuntimeError("只能检查已入库成片")
        local = self._materialize(entity["id"])
        info = probe(local)
        problems = check_spec(float(info.get("duration") or 0), info.get("width"), info.get("height"), entity["data"].get("resolution") or "")
        detail = dict(job["detail"])
        detail.update({"probe": info, "problems": problems, "passed": not problems, "clip_id": entity["id"]})
        return detail

    def _frame(self, job: dict) -> dict:
        entity = self.store.get_entity(job["target_id"])
        if entity["type"] != "Clip" or not entity.get("object_key"):
            raise RuntimeError("只能从已入库成片抽帧")
        role = (job["detail"] or {}).get("role") or "空间"
        if role not in {"首帧", "尾帧", "空间"}:
            raise RuntimeError("抽帧用途只能是首帧、尾帧或空间")
        at = (job["detail"] or {}).get("at") or "last"
        local = self._materialize(entity["id"])
        info = probe(local)
        second = 0 if at == "first" else max(0, float(info.get("duration") or 0) - 0.1)
        dest = self.data / "tmp" / f"{job['id']}.jpg"
        frame_at(local, dest, second)
        key = self.storage.put("references", f"{job['id']}.jpg", dest.read_bytes(), "image/jpeg")
        title = "上一镜尾帧" if at == "last" else "成片首帧"
        ref = self.store.add_entity("Reference", {
            "title": title,
            "role": role,
            "take": "只采用画面里的空间和人物位置",
            "ignore": "不采用这一帧里已经结束的动作",
        }, key)
        self.store.add_link("derived_from", ref["id"], entity["id"], f"抽自{at}")
        detail = dict(job["detail"])
        detail.update({"reference_id": ref["id"], "object_key": key, "at": at, "role": role})
        return detail

    def _edit(self, job: dict) -> dict:
        from .media import burn_lines, join, mix_narration, mix_score, probe

        detail = dict(job["detail"])
        op = detail.get("op") or "join"
        clip_ids = list(detail.get("clips") or [])
        narration_id = detail.get("narration") or ""
        if op == "export":
            edit = self.store.get_entity(job["target_id"])
            if not clip_ids:
                clip_ids = [link["target_id"] for link in self.store.links(edit["id"], "uses_clip")]
            narration_id = narration_id or edit["data"].get("narration") or ""
        if not clip_ids:
            raise RuntimeError("剪辑没有成片，不能导出")
        sources = [self._materialize(clip_id) for clip_id in clip_ids]
        dest = self.data / "tmp" / f"{job['id']}.mp4"
        if op == "join":
            if len(sources) < 2:
                raise RuntimeError("拼接至少要两条成片")
            join(sources, dest, fade=float(detail.get("fade") or 2.5))
        elif len(sources) >= 2:
            join(sources, dest, fade=float(detail.get("fade") or 2.5))
        else:
            dest.write_bytes(sources[0].read_bytes())
        if op == "mix":
            music_id = detail.get("music") or ""
            if not music_id:
                raise RuntimeError("剪辑没有配乐，不能混音")
            music = self._materialize(music_id, ".wav")
            narration = self._materialize(narration_id, ".wav") if narration_id else None
            mixed = self.data / "tmp" / f"{job['id']}-score.mp4"
            detail["mix"] = mix_score(dest, music, mixed, narration)
            mixed.replace(dest)
        elif op == "subtitle":
            lines = [line for line in (detail.get("lines") or []) if str(line).strip()]
            if not lines:
                raise RuntimeError("没有台词，不能烧录字幕")
            burned = self.data / "tmp" / f"{job['id']}-sub.mp4"
            burn_lines(dest, lines, burned)
            burned.replace(dest)
            detail["lines"] = lines
        elif op == "export":
            narration = self._materialize(narration_id, ".wav") if narration_id else self._voice_bed(job["id"])
            mixed = self.data / "tmp" / f"{job['id']}-mix.mp4"
            detail["mix"] = mix_narration(dest, narration, mixed)
            mixed.replace(dest)
        info = probe(dest)
        key = self.storage.put("renders", f"{job['id']}.mp4", dest.read_bytes(), "video/mp4")
        clip = self.store.add_entity("Clip", {
            "title": detail.get("title") or "剪辑成片",
            "duration": info["duration"],
        }, key)
        if clip_ids:
            self.store.add_link("derived_from", clip["id"], clip_ids[0], "由剪辑导出")
        detail.update({"clip_id": clip["id"], "object_key": key, "probe": info, "clips": clip_ids})
        return detail

    def _voice_bed(self, job_id: str) -> Path:
        """Spoken bed used when export has picture clips but no IndexTTS2 narration yet."""
        path = self.data / "tmp" / f"{job_id}-voice.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        from .media import _run, MediaError

        result = _run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", "sine=frequency=220:duration=1:sample_rate=44100",
            "-c:a", "pcm_s16le", str(path),
        ])
        if result.returncode != 0:
            raise MediaError(result.stderr.decode("utf-8", "replace")[:400])
        return path

    def _materialize(self, entity_id: str, fallback_suffix: str = ".mp4") -> Path:
        entity = self.store.get_entity(entity_id)
        if not entity.get("object_key"):
            raise RuntimeError(f"{entity_id} 没有文件")
        suffix = Path(entity["object_key"]).suffix or fallback_suffix
        path = self.data / "tmp" / f"{entity_id}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.storage.get(entity["object_key"]))
        return path

    def _ffmpeg(self, job: dict) -> dict:
        from . import media as media_module

        if not passthrough_allowed(self.store.setting("ffmpeg_passthrough", "0")):
            raise RuntimeError("ffmpeg 透传没有打开")
        work = self.data / "tmp" / job["id"]
        work.mkdir(parents=True, exist_ok=True)
        result = media_module.passthrough(job["detail"].get("args") or [], work)
        detail = dict(job["detail"])
        detail["result"] = result
        return detail
