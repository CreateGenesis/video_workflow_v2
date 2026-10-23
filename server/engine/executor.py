"""Run one claimed task to an end state. Every failure mode maps to retry, fail, park or cancel."""

from __future__ import annotations

import logging
import shutil
import traceback

from .. import db
from ..auth import worker_principal
from ..config import get_settings
from ..graph import GraphError, NotFound
from ..media import MediaError
from ..providers.base import InputError, ProviderError, SubmissionUnknown, TransientError
from . import tasks as task_q
from .generate import PREPARE, Park, run_provider
from .job import Canceled, Job
from .local import LOCAL

log = logging.getLogger("cvgen.executor")


def _after(conn, task: dict, principal) -> None:
    from ..workflows.runner import advance

    if task.get("run_id"):
        advance(conn, task["run_id"], principal)


def execute(task: dict, worker_id: str) -> str:
    from ..workflows.llm_step import run_llm
    from ..workflows.runner import RunError
    from ..workflows.template import TemplateError

    principal = worker_principal(worker_id)
    workdir = get_settings().tmp_dir / task["id"]
    workdir.mkdir(parents=True, exist_ok=True)
    job = Job(task=task, principal=principal, workdir=workdir)
    try:
        if task["kind"] == "llm":
            run_llm(job)
        elif task["kind"] in PREPARE:
            run_provider(job)
        elif task["kind"] in LOCAL:
            LOCAL[task["kind"]](job)
        else:
            raise InputError(f"不认识的任务类型 {task['kind']}")
        return "succeeded"
    except Canceled:
        with db.tx() as conn:
            task_q.mark_canceled(conn, task["id"])
            _after(conn, task, principal)
        return "canceled"
    except Park as exc:
        with db.tx() as conn:
            task_q.park(conn, task["id"], str(exc))
            _after(conn, task, principal)
        return "needs_attention"
    except SubmissionUnknown as exc:
        with db.tx() as conn:
            if task["retry_safe"]:
                outcome = task_q.fail(conn, task["id"], {"message": str(exc), "kind": "submission_unknown"}, retry=True)
            else:
                task_q.park(conn, task["id"], f"{exc}。不自动重发：请到上游核对后选择重新查询、标记失败或强制重提。")
                outcome = "needs_attention"
            _after(conn, task, principal)
        return outcome
    except (InputError, GraphError, NotFound, TemplateError, RunError, KeyError, LookupError) as exc:
        message = str(exc) if not isinstance(exc, KeyError) else f"缺少字段 {exc}"
        with db.tx() as conn:
            outcome = task_q.fail(conn, task["id"], {"message": message, "kind": "input"}, retry=False)
            _after(conn, task, principal)
        return outcome
    except (ProviderError, TransientError) as exc:
        with db.tx() as conn:
            if isinstance(exc, TransientError) and not task["retry_safe"]:
                task_q.park(conn, task["id"], f"{exc}。按次计费的供应商不自动重试，请核对后处理。")
                outcome = "needs_attention"
            else:
                outcome = task_q.fail(conn, task["id"], {"message": str(exc), "kind": "provider"}, retry=task["retry_safe"])
            _after(conn, task, principal)
        return outcome
    except MediaError as exc:
        with db.tx() as conn:
            outcome = task_q.fail(conn, task["id"], {"message": str(exc), "kind": "media"}, retry=True)
            _after(conn, task, principal)
        return outcome
    except Exception as exc:  # a bug: record it on the task so it is visible, do not retry blindly
        log.exception("task %s crashed", task["id"])
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        with db.tx() as conn:
            outcome = task_q.fail(conn, task["id"], {"message": f"内部错误：{detail}", "kind": "internal",
                                                     "trace": traceback.format_exc()[-2000:]}, retry=False)
            _after(conn, task, principal)
        return outcome
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
