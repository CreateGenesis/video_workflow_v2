import { duration } from "./format.js";

export function poolEtaLabel(pool) {
  if (!pool?.ready) return "—";
  return pool.eta_seconds ? duration(pool.eta_seconds) : "暂无历史";
}

export function taskEtaLabel(task) {
  return task?.eta_seconds ? `预计 ${duration(task.eta_seconds)}` : "暂无历史";
}
