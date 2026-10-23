"""Worker process: python -m server.worker [--pools gpu1,image-api] [--threads 4].

Claims tasks from PostgreSQL, runs each in a thread, renews leases, wakes on NOTIFY, recovers
crashed peers' tasks, delivers webhooks, and probes GPU hosts. Many workers can run at once.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select, text, update

from .. import db
from ..config import get_settings
from . import tasks as task_q
from .executor import execute
from .webhooks import deliver_due

log = logging.getLogger("cvgen.worker")


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def maintenance() -> dict:
    """Janitor, a safety-net advance for live runs, and webhook delivery."""
    from ..workflows.runner import advance

    with db.tx() as conn:
        result = task_q.janitor(conn)
    with db.tx() as conn:
        live = conn.execute(text("""
            SELECT id FROM runs WHERE status IN ('running', 'waiting') ORDER BY random() LIMIT 20
        """)).scalars().all()
    for run_id in live:
        with db.tx() as conn:
            advance(conn, run_id)
    result["webhooks"] = deliver_due()
    return result


def probe_gpu_hosts() -> None:
    from ..providers import adapter_for
    from ..providers.instances import to_instance

    with db.tx() as conn:
        rows = conn.execute(select(db.provider_instances).where(
            db.provider_instances.c.protocol == "comfyui", db.provider_instances.c.enabled.is_(True),
        )).all()
    for row in rows:
        try:
            health = adapter_for(to_instance(row)).probe()
        except Exception as exc:  # health checks must never kill the worker
            health = {"reachable": False, "message": str(exc)[:200]}
        health["checked_at"] = db.now().isoformat()
        with db.tx() as conn:
            conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == row.name).values(health=health))


class Worker:
    def __init__(self, worker_id: str | None = None, pools: list[str] | None = None, threads: int = 4):
        self.id = worker_id or default_worker_id()
        self.pools = pools or None
        self.threads = threads
        self.active: dict[str, float] = {}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stopping = threading.Event()

    def claim(self) -> dict | None:
        with db.tx() as conn:
            return task_q.claim(conn, self.id, self.pools)

    def run_until_idle(self, limit: int = 500) -> int:
        """Synchronous loop for tests and one-off use: run tasks until nothing is claimable."""
        done = 0
        while done < limit:
            task = self.claim()
            if not task:
                maintenance()
                task = self.claim()
                if not task:
                    return done
            execute(task, self.id)
            done += 1
        return done

    def _heartbeat(self) -> None:
        while not self.stopping.wait(15):
            with self.lock:
                ids = list(self.active)
            if ids:
                try:
                    with db.tx() as conn:
                        task_q.heartbeat(conn, self.id, ids)
                except Exception:
                    log.exception("heartbeat failed")

    def _listen(self) -> None:
        import psycopg

        url = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
        while not self.stopping.is_set():
            try:
                with psycopg.connect(url, autocommit=True) as conn:
                    conn.execute("LISTEN cvgen_tasks")
                    for _notify in conn.notifies(timeout=5.0):
                        self.wake.set()
                        if self.stopping.is_set():
                            return
                    self.wake.set()
            except Exception:
                log.exception("listen connection dropped; retrying")
                time.sleep(5)

    def _run(self, task: dict) -> None:
        try:
            execute(task, self.id)
        finally:
            with self.lock:
                self.active.pop(task["id"], None)
            self.wake.set()

    def serve(self) -> None:
        log.info("worker %s pools=%s threads=%s", self.id, self.pools or "all", self.threads)
        threading.Thread(target=self._heartbeat, daemon=True).start()
        threading.Thread(target=self._listen, daemon=True).start()
        pool = ThreadPoolExecutor(max_workers=self.threads, thread_name_prefix="cvgen-task")
        last_maintenance = last_probe = 0.0
        while not self.stopping.is_set():
            now = time.monotonic()
            if now - last_maintenance > 30:
                try:
                    maintenance()
                except Exception:
                    log.exception("maintenance failed")
                last_maintenance = now
            if now - last_probe > 60:
                threading.Thread(target=probe_gpu_hosts, daemon=True).start()
                last_probe = now
            while True:
                with self.lock:
                    if len(self.active) >= self.threads:
                        break
                try:
                    task = self.claim()
                except Exception:
                    log.exception("claim failed")
                    task = None
                if not task:
                    break
                with self.lock:
                    self.active[task["id"]] = time.monotonic()
                pool.submit(self._run, task)
            self.wake.wait(timeout=5)
            self.wake.clear()
        pool.shutdown(wait=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="cvgen worker")
    parser.add_argument("--pools", default="", help="逗号分隔的资源池，空表示全部")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--id", default="")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    pools = [item.strip() for item in args.pools.split(",") if item.strip()]
    Worker(args.id or None, pools or None, args.threads).serve()
