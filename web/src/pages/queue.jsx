import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, BellRing, CheckCircle2, Cpu, Hourglass, Pencil, Server } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Progress, Switch, Tooltip } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { EmptyState, ErrorState, PageHeader, SkeletonRows, Time, useConfirm, useDocumentTitle } from "@/components/common";
import { TaskRow } from "@/components/tasks";
import { api } from "@/lib/api";
import { itemLabel, shortId } from "@/lib/format";
import { kindLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { poolEtaLabel, taskEtaLabel } from "@/lib/eta-label";
import { cn } from "@/lib/utils";

export default function QueuePage() {
  const { can } = useSession();
  useDocumentTitle("队列");
  const queue = useQuery({ queryKey: ["queue"], queryFn: () => api.get("/api/queue"), refetchInterval: 15_000 });

  if (queue.isError) {
    return (
      <div>
        <PageHeader title="队列" />
        <ErrorState error={queue.error} retry={queue.refetch} />
      </div>
    );
  }
  const data = queue.data;
  return (
    <div className="space-y-5">
      <PageHeader title="队列" description="所有运行与 agent 探索任务共用一个队列，按资源池控制并发。数据实时刷新。" />
      {queue.isLoading ? (
        <SkeletonRows rows={6} />
      ) : (
        <>
          <Pools pools={data.pools} instances={data.instances} canManage={can("queue:manage")} />
          <Card>
            <CardHeader>
              <div>
                <CardTitle className="flex items-center gap-2">
                  <BellRing className="size-4 text-[#ffa931]" />
                  需要人处理
                </CardTitle>
                <p className="text-[13px] text-muted-foreground">待审批的闸门、超过审批阈值的任务、状态不明的付费任务</p>
              </div>
              <span className="tnum text-[13px] text-muted-foreground">{data.attention.length} 项</span>
            </CardHeader>
            {data.attention.length ? (
              <div className="divide-y">
                {data.attention.map((task) => (
                  <TaskRow key={task.id} task={task} showContext />
                ))}
              </div>
            ) : (
              <CardContent>
                <EmptyState compact icon={CheckCircle2} title="没有需要处理的任务" description="出现异常或需要审批时会列在这里。" />
              </CardContent>
            )}
          </Card>
          <div className="grid gap-5 xl:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Cpu className="size-4 text-primary" />
                  正在执行
                </CardTitle>
                <span className="tnum text-[13px] text-muted-foreground">{data.active.length} 个</span>
              </CardHeader>
              {data.active.length ? (
                <div className="divide-y">
                  {data.active.map((task) => (
                    <TaskRow key={task.id} task={task} showContext compact />
                  ))}
                </div>
              ) : (
                <CardContent>
                  <EmptyState compact icon={Cpu} title="现在没有任务在执行" description="资源池空闲。" />
                </CardContent>
              )}
            </Card>
            <ReadyQueue ready={data.ready} canManage={can("queue:manage")} />
          </div>
        </>
      )}
    </div>
  );
}

function healthTone(health) {
  if (!health || !Object.keys(health).length) return { tone: "gray", label: "未检查" };
  if (health.reachable === false) return { tone: "red", label: "异常" };
  if (health.reachable) return { tone: "green", label: "正常" };
  return { tone: "gray", label: "未知" };
}

export function Pools({ pools, instances, canManage }) {
  const client = useQueryClient();
  const confirm = useConfirm();
  const [editing, setEditing] = useState(null);
  const update = useMutation({
    mutationFn: ({ name, body }) => api.patch(`/api/admin/pools/${name}`, body),
    onSuccess: (_d, { name, body }) => {
      toast.success(body.paused === true ? `已暂停 ${name}` : body.paused === false ? `已恢复 ${name}` : `已更新 ${name}`);
      client.invalidateQueries();
    },
  });
  const togglePause = (pool, paused) => {
    if (paused) {
      confirm({
        title: `暂停资源池 ${pool.name}？`,
        description: "暂停后不再领取新任务；正在执行的任务会继续完成。",
        confirmText: "暂停",
        action: () => update.mutateAsync({ name: pool.name, body: { paused: true } }),
      });
    } else {
      update.mutate({ name: pool.name, body: { paused: false } });
    }
  };
  const visible = pools.filter((pool) => pool.name !== "gate");
  return (
    <div>
      <h2 className="mb-2 text-[15px] font-semibold">资源池</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {visible.map((pool) => {
          const members = instances.filter((item) => item.pool === pool.name);
          return (
            <Card key={pool.name} className={cn("p-4", pool.paused && "bg-[#171718]")}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    {pool.name}
                    {pool.paused ? <Badge tone="violet">已暂停</Badge> : null}
                  </p>
                  {pool.note ? <p className="truncate text-xs text-muted-foreground">{pool.note}</p> : null}
                </div>
                {canManage ? (
                  <div className="flex items-center gap-1.5">
                    <Tooltip content={pool.paused ? "恢复领取" : "暂停领取"}>
                      <span>
                        <Switch checked={!pool.paused} onCheckedChange={(on) => togglePause(pool, !on)} aria-label={`${pool.name} 运行开关`} />
                      </span>
                    </Tooltip>
                    <Button size="icon-sm" variant="ghost" onClick={() => setEditing(pool)} aria-label="编辑">
                      <Pencil />
                    </Button>
                  </div>
                ) : null}
              </div>
              <div className="mt-3 flex items-baseline justify-between text-[13px]">
                <span className="text-muted-foreground">占用</span>
                <span className="tnum font-medium">
                  {pool.busy} / {pool.concurrency}
                </span>
              </div>
              <Progress value={pool.concurrency ? pool.busy / pool.concurrency : 0} className="mt-1" tone={pool.paused ? "gray" : "blue"} />
              <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                <span className="tnum">
                  排队 <span className={cn("font-medium", pool.ready ? "text-[#64b5f6]" : "text-foreground")}>{pool.ready}</span>
                </span>
                <span className="tnum">预计 {poolEtaLabel(pool)}</span>
                {pool.rate_per_minute ? <span className="tnum">限 {pool.rate_per_minute} 次/分</span> : null}
              </div>
              {members.length ? (
                <div className="mt-2 flex flex-wrap gap-1 border-t pt-2">
                  {members.map((item) => {
                    const health = healthTone(item.health);
                    return (
                      <Tooltip key={item.name} content={`${item.protocol} · ${health.label}${item.enabled ? "" : " · 已停用"}`}>
                        <span className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px]", !item.enabled && "opacity-50")}>
                          <Server className="size-3 text-muted-foreground" />
                          {item.name}
                          <span className={cn("size-1.5 rounded-full", health.tone === "green" ? "bg-[#81c784]" : health.tone === "red" ? "bg-[#ff4444]" : "bg-[#4e4e4e]")} />
                        </span>
                      </Tooltip>
                    );
                  })}
                </div>
              ) : null}
            </Card>
          );
        })}
      </div>
      {editing ? (
        <PoolDialog
          pool={editing}
          onClose={() => setEditing(null)}
          onSave={async (body) => {
            await update.mutateAsync({ name: editing.name, body });
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

function PoolDialog({ pool, onClose, onSave }) {
  const [concurrency, setConcurrency] = useState(String(pool.concurrency));
  const [rate, setRate] = useState(pool.rate_per_minute ? String(pool.rate_per_minute) : "");
  const [note, setNote] = useState(pool.note || "");
  const [busy, setBusy] = useState(false);
  const bad = !/^\d+$/.test(concurrency) || Number(concurrency) < 0 || Number(concurrency) > 64;
  const save = async () => {
    if (bad) return;
    setBusy(true);
    try {
      await onSave({ concurrency: Number(concurrency), rate_per_minute: rate ? Number(rate) : null, note });
    } catch {
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>编辑资源池 {pool.name}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <Field label="并发上限" htmlFor="pool-concurrency" hint="同时执行的任务数，0 到 64。GPU 池通常每台机器 1。" error={bad ? "请输入 0–64 的整数" : ""}>
            <Input id="pool-concurrency" type="number" min={0} max={64} className="tnum" value={concurrency} onChange={(event) => setConcurrency(event.target.value)} aria-invalid={bad || undefined} />
          </Field>
          <Field label="每分钟请求上限" htmlFor="pool-rate" hint="留空表示不限">
            <Input id="pool-rate" type="number" min={0} className="tnum" value={rate} onChange={(event) => setRate(event.target.value)} />
          </Field>
          <Field label="备注" htmlFor="pool-note">
            <Input id="pool-note" value={note} onChange={(event) => setNote(event.target.value)} />
          </Field>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={save} disabled={bad} loading={busy}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReadyQueue({ ready, canManage }) {
  const client = useQueryClient();
  const priority = useMutation({
    mutationFn: ({ task, value }) => api.post(`/api/tasks/${task.id}/priority`, { priority: value }),
    onSuccess: (_d, { value }) => {
      toast.success(`优先级已改为 ${value}`);
      client.invalidateQueries({ queryKey: ["queue"] });
    },
  });
  const byPool = ready.reduce((groups, task) => {
    (groups[task.pool] = groups[task.pool] || []).push(task);
    return groups;
  }, {});
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Hourglass className="size-4 text-[#64b5f6]" />
            排队顺序
          </CardTitle>
          <p className="text-[13px] text-muted-foreground">每个资源池内按优先级、发起顺序领取</p>
        </div>
        <span className="tnum text-[13px] text-muted-foreground">{ready.length} 个</span>
      </CardHeader>
      {ready.length ? (
        <div className="divide-y">
          {Object.entries(byPool).map(([pool, tasks]) => (
            <div key={pool} className="px-4 py-3">
              <p className="mb-1.5 text-xs font-medium text-muted-foreground">{pool}</p>
              <ol className="space-y-1">
                {tasks.map((task, index) => (
                  <li key={task.id} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-[13px] hover:bg-[#303030]">
                    <span className="tnum w-6 text-right text-xs text-muted-foreground">{index + 1}</span>
                    <span className="font-medium">{kindLabel(task.kind)}</span>
                    {task.item !== "" ? <span className="text-muted-foreground">{itemLabel(task.item, task.item_index)}</span> : null}
                    {task.run_id ? (
                      <Link className="truncate text-primary hover:underline" to={`/runs/${task.run_id}`}>
                        运行 {shortId(task.run_id)}
                      </Link>
                    ) : task.work_id ? (
                      <Link className="truncate text-primary hover:underline" to={`/explore/${task.work_id}`}>
                        探索
                      </Link>
                    ) : null}
                    <span className="flex-1" />
                    <span className="tnum text-xs text-muted-foreground" data-testid={`eta-${task.id}`}>
                      {taskEtaLabel(task)}
                    </span>
                    <span className="hidden text-xs text-muted-foreground sm:inline">
                      <Time value={task.created_at} />
                    </span>
                    <span className="tnum w-12 text-right text-xs text-muted-foreground">P{task.priority}</span>
                    {canManage ? (
                      <span className="flex">
                        <Tooltip content="提高优先级 +10">
                          <Button size="icon-sm" variant="ghost" className="size-6" onClick={() => priority.mutate({ task, value: (task.priority || 0) + 10 })} aria-label="提高优先级">
                            <ArrowUp className="!size-3.5" />
                          </Button>
                        </Tooltip>
                        <Tooltip content="降低优先级 -10">
                          <Button size="icon-sm" variant="ghost" className="size-6" onClick={() => priority.mutate({ task, value: (task.priority || 0) - 10 })} aria-label="降低优先级">
                            <ArrowDown className="!size-3.5" />
                          </Button>
                        </Tooltip>
                      </span>
                    ) : null}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      ) : (
        <CardContent>
          <EmptyState compact icon={Hourglass} title="队列是空的" description="新任务就绪后会按顺序排在这里。" />
        </CardContent>
      )}
    </Card>
  );
}
