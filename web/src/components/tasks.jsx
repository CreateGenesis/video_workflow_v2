import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Ban, CheckCheck, RotateCcw, Search, ShieldCheck, XOctagon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress, Tooltip } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { Money, TaskStatus, Time, useConfirm } from "@/components/common";
import { Thumb } from "@/components/media";
import { api } from "@/lib/api";
import { duration, elapsed, itemLabel, shortId } from "@/lib/format";
import { ACTIVE_TASK, OPEN_TASK, kindLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

export function useTaskActions() {
  const client = useQueryClient();
  const confirm = useConfirm();
  const { me, can } = useSession();

  const refresh = () => client.invalidateQueries();

  const cancel = useMutation({
    mutationFn: (task) => api.post(`/api/tasks/${task.id}/cancel`),
    onSuccess: () => {
      toast.success("已请求取消", "正在执行的任务会在供应商确认后停止");
      refresh();
    },
  });

  const canCancel = (task) => {
    if (!OPEN_TASK.includes(task.status) || task.kind === "gate" || task.cancel_requested) return false;
    const own = task.created_by === `${me.kind}:${me.id}`;
    return own || can("queue:manage") || can("works:write");
  };

  const askCancel = (task) =>
    confirm({
      title: "取消这个任务？",
      description: `${kindLabel(task.kind)}任务 ${shortId(task.id)}。已经提交给供应商的任务可能已经产生费用，取消后产物仍会入库。`,
      confirmText: "取消任务",
      danger: true,
      action: () => cancel.mutateAsync(task),
    });

  const resolve = useMutation({
    mutationFn: ({ task, action }) => api.post(`/api/tasks/${task.id}/resolve`, { action }),
    onSuccess: (_data, { action }) => {
      const text = { approve: "已批准，任务进入队列", requery: "已重新查询上游状态", fail: "已标记为失败", resubmit: "已重新提交到队列" };
      toast.success(text[action] || "已处理");
      refresh();
    },
  });

  const attentionActions = (task) => {
    if (task.status !== "needs_attention") return [];
    const list = [];
    const isApproval = /批准|审批/.test(task.attention || "");
    if (isApproval && can("workflows:publish")) list.push("approve");
    if (can("tasks:resolve")) {
      if (!isApproval) list.push("requery");
      list.push("resubmit", "fail");
    }
    return list;
  };

  const askResolve = (task, action) => {
    const what = `${kindLabel(task.kind)}任务 ${shortId(task.id)}`;
    const options = {
      approve: {
        title: "批准执行这个任务？",
        description: `${what}\n${task.attention || ""}`,
        confirmText: "批准并执行",
        spends: true,
      },
      requery: {
        title: "重新查询上游状态？",
        description: `${what} 会按已记录的上游任务号去供应商那里查结果，不会重复提交。`,
        confirmText: "重新查询",
      },
      resubmit: {
        title: "强制重新提交？",
        description: `${what} 会作为新任务重新提交给供应商。如果上一次其实已经成功，会重复扣费。`,
        confirmText: "强制重提",
        spends: true,
        danger: true,
      },
      fail: {
        title: "把任务标记为失败？",
        description: `${what} 会结束；所在运行也会因此失败。这个操作不能撤销。`,
        confirmText: "标记失败",
        danger: true,
      },
    }[action];
    return confirm({ ...options, action: () => resolve.mutateAsync({ task, action }) });
  };

  return { canCancel, askCancel, attentionActions, askResolve };
}

const ACTION_ICONS = { approve: ShieldCheck, requery: Search, resubmit: RotateCcw, fail: XOctagon };
const ACTION_TEXT = { approve: "批准", requery: "重新查询", resubmit: "强制重提", fail: "标记失败" };

export function TaskActions({ task, size = "xs" }) {
  const { canCancel, askCancel, attentionActions, askResolve } = useTaskActions();
  const actions = attentionActions(task);
  const showCancel = canCancel(task);
  if (!actions.length && !showCancel && !(task.kind === "gate" && task.status === "waiting" && task.run_id)) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {task.kind === "gate" && task.status === "waiting" && task.run_id ? (
        <Button asChild size={size}>
          <Link to={`/runs/${task.run_id}#gate`}>
            <CheckCheck />
            去审批
          </Link>
        </Button>
      ) : null}
      {actions.map((action) => {
        const Icon = ACTION_ICONS[action];
        return (
          <Button
            key={action}
            size={size}
            variant={action === "approve" ? "default" : action === "fail" ? "destructive-outline" : "outline"}
            onClick={() => askResolve(task, action)}
          >
            <Icon />
            {ACTION_TEXT[action]}
          </Button>
        );
      })}
      {showCancel ? (
        <Button size={size} variant="ghost" className="text-muted-foreground" onClick={() => askCancel(task)}>
          <Ban />
          取消
        </Button>
      ) : null}
    </div>
  );
}

/** Media found in a task's output summary: candidates, a single artifact, or an exported clip. */
export function taskMedia(task) {
  const output = task.output || {};
  if (Array.isArray(output.candidates) && output.candidates.length) {
    return output.candidates.map((candidate, index) => ({
      url: candidate.url,
      kind: "image",
      label: `候选 ${index + 1}`,
      entity_id: candidate.entity_id,
      chosen: output.attached === candidate.entity_id,
    }));
  }
  const list = [];
  if (output.url) list.push({ url: output.url, kind: task.kind === "video" || task.kind === "edit" ? "video" : task.kind === "image" ? "image" : task.kind === "tts" || task.kind === "music" ? "audio" : "file", label: "" });
  if (output.sheet_url) list.push({ url: output.sheet_url, kind: "image", label: "接触表" });
  if (output.last_frame_url) list.push({ url: output.last_frame_url, kind: "image", label: "尾帧" });
  return list;
}

export function TaskRow({ task, showContext = false, className, compact = false }) {
  const active = ACTIVE_TASK.includes(task.status);
  const media = compact ? [] : taskMedia(task);
  const spent = task.finished_at || task.started_at ? elapsed(task.started_at || task.created_at, task.finished_at) : null;
  return (
    <div className={cn("flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start", className)}>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <TaskStatus status={task.status} />
          <span className="text-sm font-medium">{kindLabel(task.kind)}</span>
          {task.node_id ? <span className="text-[13px] text-muted-foreground">步骤 {task.node_id}</span> : null}
          {task.item !== "" && task.item !== null && task.item !== undefined ? (
            <span className="text-[13px] text-muted-foreground">{itemLabel(task.item, task.item_index)}</span>
          ) : null}
          {task.provider ? <span className="text-xs text-muted-foreground">· {task.provider}</span> : null}
          {task.superseded_by ? <span className="text-xs text-muted-foreground">· 已被新任务替换</span> : null}
        </div>
        {active ? (
          <div className="flex items-center gap-2">
            <Progress value={task.progress} className="max-w-64" />
            <span className="tnum text-xs text-muted-foreground">{Math.round((task.progress || 0) * 100)}%</span>
            {task.progress_message ? <span className="truncate text-xs text-muted-foreground">{task.progress_message}</span> : null}
          </div>
        ) : null}
        {task.attention ? (
          <p className="flex items-start gap-1.5 text-[13px] text-[#ffa931]">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
            {task.attention}
          </p>
        ) : task.error && task.status === "failed" ? (
          <p className="flex items-start gap-1.5 text-[13px] text-[#ff9c9c]">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
            <span className="break-words">{task.error}</span>
          </p>
        ) : null}
        {media.length ? (
          <div className="flex flex-wrap gap-1.5">
            {media.slice(0, 6).map((item, index) => (
              <div key={index} className="w-28">
                <Thumb artifact={item} label={item.label} selected={item.chosen} />
              </div>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
          <span>
            创建于 <Time value={task.created_at} />
          </span>
          {spent !== null && task.started_at ? <span className="tnum">耗时 {duration(spent)}</span> : null}
          {task.attempts > 1 ? <span className="tnum">第 {task.attempts} 次尝试</span> : null}
          {task.cost_yuan ? (
            <span>
              花费 <Money value={task.cost_yuan} />
            </span>
          ) : null}
          {showContext && task.run_id ? (
            <Link className="text-primary hover:underline" to={`/runs/${task.run_id}`}>
              运行 {shortId(task.run_id)}
            </Link>
          ) : null}
          {showContext && !task.run_id && task.work_id ? (
            <Link className="text-primary hover:underline" to={`/explore/${task.work_id}`}>
              作品 {shortId(task.work_id)}
            </Link>
          ) : null}
          <Tooltip content={task.id}>
            <span className="font-mono text-[11px]">{shortId(task.id)}</span>
          </Tooltip>
        </div>
      </div>
      <TaskActions task={task} />
    </div>
  );
}
