"""What an executor knows about the task it runs: its row, its run, its scope, its working directory."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from .. import artifacts, db, graph
from ..auth import Principal
from ..providers import adapter_for
from ..providers.base import Adapter, Instance, TaskContext
from ..providers.instances import get_row, resolve, to_instance
from . import tasks as task_q


class Canceled(Exception):
    pass


@dataclass
class Job:
    task: dict
    principal: Principal
    workdir: Path
    _cancel_checked: float = 0.0
    _cancel: bool = False
    logs: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.task["id"]

    @property
    def input(self) -> dict:
        return self.task.get("input") or {}

    @property
    def node(self) -> dict:
        return self.input.get("node") or {}

    @property
    def is_workflow(self) -> bool:
        return bool(self.task.get("run_id"))

    def cancel_requested(self) -> bool:
        if self._cancel:
            return True
        if time.monotonic() - self._cancel_checked > 3:
            with db.tx() as conn:
                self._cancel = task_q.cancel_requested(conn, self.id)
            self._cancel_checked = time.monotonic()
        return self._cancel

    def context(self) -> TaskContext:
        return TaskContext(task_id=self.id, workdir=self.workdir, cancel_requested=self.cancel_requested,
                           log=self.logs.append)

    def instance(self, conn) -> Instance:
        """The instance this task runs on. Group refs pick a member by the slot the task holds."""
        ref = (self.task.get("provider_ref") or {}).get("_instance")
        if ref:
            row = get_row(conn, ref)
            if row:
                return to_instance(row)
        candidates = resolve(conn, self.task["provider_instance"], self.task["kind"]) if self.task.get("provider_instance") else []
        if not candidates:
            raise RuntimeError(f"没有可用的供应商实例 {self.task.get('provider_instance')}")
        in_pool = [item for item in candidates if item.pool == self.task["pool"]] or candidates
        return in_pool[int(self.task.get("slot") or 0) % len(in_pool)]

    def adapter(self, conn) -> tuple[Instance, Adapter]:
        instance = self.instance(conn)
        return instance, adapter_for(instance)

    def run_row(self, conn) -> dict | None:
        if not self.task.get("run_id"):
            return None
        return dict(conn.execute(select(db.runs).where(db.runs.c.id == self.task["run_id"])).mappings().one())

    def spec(self, conn) -> dict:
        from ..workflows.runner import get_version

        run = self.run_row(conn)
        return get_version(conn, run["workflow_id"], run["version"], published_only=False)["spec"]

    def scope(self, conn):
        from ..workflows.runner import scope_for

        run = self.run_row(conn)
        item = self.input.get("item")
        if self.input.get("item_is_entity") and item:
            from ..workflows.template import EntityRef

            item = EntityRef(item)
        return scope_for(conn, run, self.spec(conn), item=item, item_index=self.task.get("item_index", 0))

    def graph(self, conn) -> graph.DbGraph:
        return graph.DbGraph(conn, self.task["workspace_id"])

    def prefix(self) -> str:
        if self.task.get("run_id"):
            item = self.task.get("item_key") or "all"
            return f"runs/{self.task['run_id']}/{self.task.get('node_id') or 'task'}/{item}"
        return f"works/{self.task.get('work_id') or 'none'}/{self.id}"

    def store(self, conn, path: Path, **kwargs) -> dict:
        return artifacts.store_file(conn, self.task["workspace_id"], path, prefix=self.prefix(),
                                    produced_by_task=self.id, **kwargs)

    def local(self, conn, artifact_id: str) -> Path:
        return artifacts.fetch_local(conn, artifact_id, self.workdir)

    def upstream_output(self, conn, node_id: str) -> dict:
        """The output of another node for the same item (for example the clip a check looks at)."""
        row = conn.execute(select(db.tasks.c.output).where(
            db.tasks.c.run_id == self.task["run_id"], db.tasks.c.node_id == node_id,
            db.tasks.c.item_key == self.task["item_key"], db.tasks.c.superseded_by.is_(None),
        )).first()
        return dict(row.output or {}) if row else {}
