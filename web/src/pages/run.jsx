import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Clock,
  Download,
  FileVideo,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
  Telescope,
  ThumbsDown,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress, Skeleton, TBody, THead, Table, Tooltip } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import {
  Collapsible,
  EmptyState,
  ErrorState,
  IdText,
  JsonView,
  KeyValues,
  Money,
  Notice,
  PageHeader,
  RunStatus,
  SkeletonRows,
  TaskStatus,
  Time,
  useConfirm,
  useDocumentTitle,
} from "@/components/common";
import { CompileResult } from "@/components/compile-result";
import { DownloadLink, Thumb, VideoPlayer } from "@/components/media";
import { TaskActions, taskMedia } from "@/components/tasks";
import { api, downloadUrl } from "@/lib/api";
import { duration, elapsed, itemLabel, shortId } from "@/lib/format";
import { ACTIVE_TASK, PRICING_UNIT, ROLE, RUN_MODE, TERMINAL_RUN, kindLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { ActivityList, NotesPanel } from "@/pages/work";

export default function RunPage() {
  const { id } = useParams();
  const { can } = useSession();
  const location = useLocation();
  const run = useQuery({ queryKey: ["run", id], queryFn: () => api.get(`/api/runs/${id}`) });
  const data = run.data;
  const board = useQuery({
    queryKey: ["storyboard", data?.work_id],
    queryFn: () => api.get(`/api/works/${data.work_id}/storyboard`),
    enabled: Boolean(data?.work_id) && can("works:read"),
  });
  useDocumentTitle(data ? `${data.workflow_name} 运行` : "运行");

  useEffect(() => {
    if (location.hash === "#gate" && data) document.getElementById("gate")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [location.hash, data]);

  if (run.isError) {
    return (
      <div>
        <PageHeader title="运行" back={{ to: "/runs", label: "运行" }} />
        <ErrorState error={run.error} retry={run.refetch} />
      </div>
    );
  }
  if (run.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-72" />
        <div className="grid gap-3 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
        <SkeletonRows rows={5} />
      </div>
    );
  }

  const shots = board.data?.shots || [];
  const gates = data.nodes.flatMap((node) => node.tasks.filter((task) => task.kind === "gate" && task.status === "waiting").map((task) => ({ node, task })));

  return (
    <div className="space-y-5">
      <RunHeader data={data} />
      <RunSummary data={data} />
      {data.error ? (
        <div className="flex items-start gap-2 rounded-lg border border-[#6a2424] bg-[#3a1717] px-4 py-3" role="alert">
          <XCircle className="mt-0.5 size-4 shrink-0 text-[#ff4444]" />
          <div className="text-[13px]">
            <p className="font-medium text-[#ff6e6e]">运行没有成功</p>
            <p className="text-[#ff9c9c]">
              {data.error.message}
              {data.error.node ? `（步骤 ${data.error.node}${data.error.item ? ` · ${itemLabel(data.error.item)}` : ""}）` : ""}
            </p>
          </div>
        </div>
      ) : null}
      {data.status === "paused" ? (
        <Notice tone="warn" icon={Pause}>
          运行已暂停：已提交的任务会继续完成，新的任务不会开始。{Number(data.cost_actual) > Number(data.spec?.budget?.max_yuan || Infinity) ? "原因：花费超过预算上限。" : ""}
        </Notice>
      ) : null}
      {gates.map(({ node, task }) => (
        <GatePanel key={task.id} run={data} gateNode={node} task={task} shots={shots} />
      ))}
      <Outputs data={data} />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Timeline data={data} shots={shots} />
        <div className="space-y-5">
          <InputsCard data={data} />
          <CostsCard data={data} />
        </div>
      </div>
      <Tabs defaultValue={can("activity:read") ? "activity" : "notes"}>
        <TabsList>
          {can("activity:read") ? <TabsTrigger value="activity">活动</TabsTrigger> : null}
          {can("notes:read") ? <TabsTrigger value="notes">审计意见</TabsTrigger> : null}
          <TabsTrigger value="spec">工作流规格</TabsTrigger>
        </TabsList>
        {can("activity:read") ? (
          <TabsContent value="activity">
            <ActivityList runId={data.id} />
          </TabsContent>
        ) : null}
        {can("notes:read") ? (
          <TabsContent value="notes">
            <NotesPanel runId={data.id} workId={data.work_id} workspaceId={data.workspace_id} />
          </TabsContent>
        ) : null}
        <TabsContent value="spec">
          <JsonView value={data.spec} maxHeight="36rem" />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function RunHeader({ data }) {
  const { can, me } = useSession();
  const confirm = useConfirm();
  const client = useQueryClient();
  const refresh = () => client.invalidateQueries();
  const terminal = TERMINAL_RUN.includes(data.status);
  const pause = useMutation({
    mutationFn: (paused) => api.post(`/api/runs/${data.id}/${paused ? "pause" : "resume"}`),
    onSuccess: (_d, paused) => {
      toast.success(paused ? "已暂停" : "已继续", paused ? "已经提交的任务会继续完成" : "任务重新开始排队");
      refresh();
    },
  });
  const cancel = useMutation({
    mutationFn: () => api.post(`/api/runs/${data.id}/cancel`),
    onSuccess: () => {
      toast.success("运行已取消");
      refresh();
    },
  });
  const canCancel = can("runs:create") || data.created_by_id === me.id;
  return (
    <PageHeader
      back={{ to: "/runs", label: "运行" }}
      title={
        <span className="flex items-center gap-2">
          {data.workflow_name}
          <Link to={`/workflows/${data.workflow_id}/v/${data.version}`} className="tnum text-base font-normal text-muted-foreground hover:underline">
            v{data.version}
          </Link>
        </span>
      }
      meta={
        <>
          <RunStatus status={data.status} />
          {data.mode !== "production" ? <Badge tone="violet">{RUN_MODE[data.mode]?.label || data.mode}</Badge> : null}
          {data.batch_id ? <Badge>批量</Badge> : null}
        </>
      }
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>
            发起于 <Time value={data.created_at} />
          </span>
          {data.finished_at ? (
            <span>
              结束于 <Time value={data.finished_at} />
            </span>
          ) : null}
          {data.priority ? <span className="tnum">优先级 {data.priority > 0 ? `+${data.priority}` : data.priority}</span> : null}
          {data.auto_gates ? <span>闸门自动通过</span> : null}
          <IdText id={data.id} />
        </span>
      }
      actions={
        <>
          {data.work_id && can("works:read") ? (
            <Button asChild variant="outline" size="sm">
              <Link to={`/explore/${data.work_id}`}>
                <Telescope />
                分镜与关系图
              </Link>
            </Button>
          ) : null}
          {!terminal && can("runs:create") ? (
            data.status === "paused" ? (
              <Button size="sm" variant="outline" onClick={() => pause.mutate(false)} loading={pause.isPending}>
                <Play />
                继续
              </Button>
            ) : (
              <Button size="sm" variant="outline" onClick={() => pause.mutate(true)} loading={pause.isPending}>
                <Pause />
                暂停
              </Button>
            )
          ) : null}
          {!terminal && canCancel ? (
            <Button
              size="sm"
              variant="destructive-outline"
              onClick={() =>
                confirm({
                  title: "取消这个运行？",
                  description: "所有未开始的任务会被取消；已经提交给供应商的任务会请求取消，已经产生的费用不会退回。这个操作不能撤销。",
                  confirmText: "取消运行",
                  danger: true,
                  action: () => cancel.mutateAsync(),
                })
              }
            >
              <Ban />
              取消运行
            </Button>
          ) : null}
        </>
      }
    />
  );
}

function RunSummary({ data }) {
  const progress = data.progress;
  const ratio = progress.total ? progress.succeeded / progress.total : 0;
  const budget = data.spec?.budget?.max_yuan;
  const spent = elapsed(data.started_at || data.created_at, data.finished_at);
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Card className="p-4">
        <p className="text-[13px] text-muted-foreground">进度</p>
        <p className="tnum mt-1 text-xl font-semibold">
          {progress.succeeded}
          <span className="text-sm font-normal text-muted-foreground"> / {progress.total} 项完成</span>
        </p>
        <Progress value={ratio} className="mt-2" tone={data.status === "failed" ? "red" : data.status === "succeeded" ? "green" : "blue"} />
      </Card>
      <Card className="p-4">
        <p className="text-[13px] text-muted-foreground">实际花费</p>
        <p className="tnum mt-1 text-xl font-semibold">
          <Money value={data.cost_actual} digits={2} />
        </p>
        <p className="tnum mt-1 text-xs text-muted-foreground">
          估算 {data.cost_estimate ? <Money value={data.cost_estimate} digits={2} /> : "—"} · 预算 <Money value={budget} digits={2} />
        </p>
      </Card>
      <Card className="p-4">
        <p className="text-[13px] text-muted-foreground">正在执行</p>
        <p className="tnum mt-1 text-xl font-semibold">{progress.active}</p>
        <p className="mt-1 text-xs text-muted-foreground">{progress.waiting ? <span className="text-[#ffa931]">{progress.waiting} 项等人处理</span> : progress.ready ? (progress.eta_seconds ? `排队预计 ${duration(progress.eta_seconds)}` : "排队中，还没有同类历史耗时") : "没有等待处理的项"}</p>
      </Card>
      <Card className="p-4">
        <p className="text-[13px] text-muted-foreground">{data.finished_at ? "总耗时" : "已运行"}</p>
        <p className="tnum mt-1 text-xl font-semibold">{duration(spent)}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          <Time value={data.started_at || data.created_at} /> 开始
        </p>
      </Card>
    </div>
  );
}

/* ---------- gate ---------- */

function GatePanel({ run, gateNode, task, shots }) {
  const { can } = useSession();
  const confirm = useConfirm();
  const client = useQueryClient();
  const spec = run.spec || {};
  const gate = (spec.nodes || []).find((node) => node.id === gateNode.id) || {};
  const approvers = gate.approvers || "reviewer";
  const allowed = can(`gates:decide:${approvers}`);
  const shown = (gate.show || []).map((nodeId) => run.nodes.find((node) => node.id === nodeId)).filter(Boolean);
  const [selections, setSelections] = useState({});
  const [redo, setRedo] = useState([]);

  const decide = useMutation({
    mutationFn: (body) => api.post(`/api/gates/${task.id}`, body),
    onSuccess: (_data, body) => {
      toast.success(body.decision === "approve" ? "已通过，后续步骤开始排队" : body.redo?.length ? `已安排重做 ${body.redo.length} 条` : "已驳回，运行结束");
      setRedo([]);
      client.invalidateQueries();
    },
  });

  const shotTitle = (index) => (typeof index === "number" && shots[index] ? shots[index].shot.data?.title : "");
  const nextNodes = run.nodes.filter((node) => (spec.nodes || []).find((item) => item.id === node.id)?.after?.includes(gateNode.id));
  const paidNext = nextNodes.some((node) => ["video", "image", "tts", "music", "llm"].includes(node.kind));

  return (
    <Card id="gate" className="scroll-mt-20 border-[#ffa931]">
      <CardHeader className="bg-[#3a2a12]">
        <div>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-[#ffa931]" />
            待审批：{gate.title || gateNode.title}
          </CardTitle>
          <p className="text-[13px] text-muted-foreground">
            需要{ROLE[approvers] || approvers}审批 · 等待了 <Time value={task.created_at} />
            {gate.timeout_hours ? ` · ${gate.timeout_hours} 小时内处理` : ""}
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {!allowed ? <Notice tone="warn" icon={AlertTriangle}>你没有审批这个闸门的权限（需要{ROLE[approvers] || approvers}）。下面的内容只供查看。</Notice> : null}
        {shown.map((node) => (
          <div key={node.id} className="space-y-2">
            <p className="text-[13px] font-medium">
              {node.title} <span className="font-normal text-muted-foreground">· {kindLabel(node.kind)}</span>
            </p>
            {node.kind === "llm" ? (
              shots.length ? (
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {shots.map((row, index) => (
                    <div key={row.shot.id} className="rounded-md border border-[#4e4e4e] bg-[#222] p-3 text-[13px]">
                      <p className="font-medium">
                        第 {index + 1} 镜 · {row.shot.data?.title}
                        {row.duration ? <span className="tnum ml-1.5 text-xs font-normal text-muted-foreground">{row.duration} 秒</span> : null}
                      </p>
                      <p className="mt-1 text-[#ccc]">{row.shot.data?.action}</p>
                      {row.shot.data?.reverse ? <p className="mt-1 text-xs text-muted-foreground">避免：{row.shot.data.reverse}</p> : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[13px] text-muted-foreground">大模型输出已写入作品。</p>
              )
            ) : (
              <div className="space-y-2">
                {node.tasks.map((item) => {
                  const media = taskMedia(item);
                  const key = `${node.id}:${item.item}`;
                  const candidates = item.output?.candidates || [];
                  const chosen = selections[key] || item.output?.attached || candidates[0]?.entity_id;
                  const marked = redo.includes(item.item);
                  return (
                    <div key={item.id} className={cn("rounded-md border p-3", marked && "border-[#fdd7c0] bg-[#3a2218]")}>
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-medium">
                          {itemLabel(item.item, item.item_index)}
                          {shotTitle(item.item_index) ? ` · ${shotTitle(item.item_index)}` : ""}
                        </span>
                        <TaskStatus status={item.status} />
                        <span className="flex-1" />
                        {allowed && gate.allow_redo !== false ? (
                          <label className="flex cursor-pointer items-center gap-1.5 text-[13px]">
                            <input
                              type="checkbox"
                              className="size-3.5 accent-[#ef6820]"
                              checked={marked}
                              onChange={(event) => setRedo((current) => (event.target.checked ? [...current, item.item] : current.filter((value) => value !== item.item)))}
                            />
                            重做这一条
                          </label>
                        ) : null}
                      </div>
                      {candidates.length > 1 ? (
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                          {candidates.map((candidate, index) => {
                            const active = chosen === candidate.entity_id;
                            return (
                              <div key={candidate.entity_id} className="space-y-1">
                                <Thumb artifact={{ url: candidate.url, kind: "image", label: `候选 ${index + 1}` }} selected={active} />
                                <button
                                  type="button"
                                  disabled={!allowed}
                                  onClick={() => setSelections((current) => ({ ...current, [key]: candidate.entity_id }))}
                                  className={cn(
                                    "flex w-full items-center justify-center gap-1 rounded-md border py-1 text-xs",
                                    active ? "border-primary bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted",
                                  )}
                                >
                                  {active ? <CheckCircle2 className="size-3.5" /> : null}
                                  {active ? `已选候选 ${index + 1}` : `选候选 ${index + 1}`}
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      ) : media.length ? (
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                          {media.map((entry, index) => (
                            <Thumb key={index} artifact={entry} label={entry.label} />
                          ))}
                        </div>
                      ) : (
                        <p className="text-[13px] text-muted-foreground">没有可预览的产物</p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ))}
        {allowed ? (
          <div className="flex flex-col gap-2 border-t pt-4 sm:flex-row sm:items-center">
            <p className="flex-1 text-[13px] text-muted-foreground">
              {redo.length ? `已勾选 ${redo.length} 条重做。` : "勾选「重做这一条」可以只重跑个别条目。"}
              {Object.keys(selections).length ? ` 已改选 ${Object.keys(selections).length} 处候选。` : ""}
            </p>
            <Button
              variant="destructive-outline"
              onClick={() =>
                confirm({
                  title: "驳回这个闸门？",
                  description: "驳回后整个运行会结束，标记为失败。之后只能重新发起运行。",
                  confirmText: "驳回并结束运行",
                  danger: true,
                  withNote: true,
                  noteRequired: true,
                  notePlaceholder: "写下驳回理由（必填），会记进活动流",
                  action: (note) => decide.mutateAsync({ decision: "reject", note }),
                })
              }
            >
              <ThumbsDown />
              驳回
            </Button>
            {gate.allow_redo !== false ? (
              <Button
                variant="outline"
                disabled={!redo.length}
                onClick={() =>
                  confirm({
                    title: `重做选中的 ${redo.length} 条？`,
                    description: `会重新生成：${redo.map((item) => itemLabel(item)).join("、")}。完成后闸门会再次等待审批。`,
                    spends: true,
                    confirmText: "重做",
                    withNote: true,
                    notePlaceholder: "告诉执行者要改什么（可选）",
                    action: (note) => decide.mutateAsync({ decision: "reject", note, redo }),
                  })
                }
              >
                <RotateCcw />
                重做选中{redo.length ? ` ${redo.length} 条` : ""}
              </Button>
            ) : null}
            <Button
              disabled={redo.length > 0}
              onClick={() =>
                confirm({
                  title: "通过这个闸门？",
                  description: `通过后会继续执行：${nextNodes.map((node) => node.title).join("、") || "后续步骤"}。${
                    shown.some((node) => node.tasks.some((item) => (item.output?.candidates || []).length > 1)) ? "每一条使用当前选中的候选图。" : ""
                  }`,
                  spends: paidNext ? "后续步骤会生成视频等付费内容" : undefined,
                  confirmText: "通过",
                  withNote: true,
                  notePlaceholder: "备注（可选）",
                  action: (note) => decide.mutateAsync({ decision: "approve", note, selections }),
                })
              }
            >
              <ShieldCheck />
              通过
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

/* ---------- outputs ---------- */

function Outputs({ data }) {
  const outputs = data.outputs || {};
  if (outputs.compiled) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>大模型试跑结果</CardTitle>
        </CardHeader>
        <CardContent>
          <CompileResult result={outputs.compiled} budget={data.spec?.budget?.max_yuan} />
        </CardContent>
      </Card>
    );
  }
  const entries = Object.entries(outputs).filter(([key, value]) => !key.startsWith("_") && Array.isArray(value) && value.length);
  const flags = outputs._flags || [];
  if (!entries.length) return null;
  const main = entries.find(([key]) => key === "video");
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>交付产物</CardTitle>
          <p className="text-[13px] text-muted-foreground">链接 1 小时内有效，过期刷新页面即可</p>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {flags.length ? (
          <Notice tone="warn" icon={AlertTriangle}>
            自动检查发现问题：
            {flags.map((flag) => `${flag.node} ${itemLabel(flag.item)}：${(flag.problems || []).join("，")}`).join("；")}
          </Notice>
        ) : null}
        {main ? (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,640px)_1fr]">
            <VideoPlayer url={main[1][0]?.url} />
            <div className="space-y-2">
              <p className="text-sm font-medium">成片</p>
              {main[1][0]?.url ? (
                <Button asChild>
                  <a href={downloadUrl(main[1][0].url)}>
                    <Download />
                    下载成片
                  </a>
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}
        {entries
          .filter(([key]) => key !== "video")
          .map(([key, items]) => (
            <div key={key}>
              <p className="mb-2 text-[13px] font-medium">
                {key} <span className="font-normal text-muted-foreground">· {items.length} 项</span>
              </p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                {items.map((item, index) => (
                  <div key={`${item.item}-${index}`} className="space-y-1">
                    <Thumb artifact={item.url ? { url: item.url, kind: /clip|video/.test(key) ? "video" : "image" } : null} label={itemLabel(item.item)} />
                    {item.url ? <DownloadLink url={item.url} className="w-full" /> : null}
                  </div>
                ))}
              </div>
            </div>
          ))}
      </CardContent>
    </Card>
  );
}

/* ---------- timeline ---------- */

function nodeState(tasks) {
  if (!tasks.length) return { label: "未开始", tone: "gray" };
  const count = (status) => tasks.filter((task) => task.status === status).length;
  if (count("failed")) return { label: "失败", tone: "red" };
  if (count("needs_attention")) return { label: "需要处理", tone: "orange" };
  if (count("waiting")) return { label: "待审批", tone: "amber" };
  if (tasks.some((task) => ACTIVE_TASK.includes(task.status))) return { label: "执行中", tone: "blue" };
  if (count("succeeded") === tasks.length) return { label: "完成", tone: "green" };
  if (count("canceled") === tasks.length) return { label: "已取消", tone: "gray" };
  if (count("ready")) return { label: "排队中", tone: "sky" };
  return { label: "等待上游", tone: "gray" };
}

const DOT = { gray: "bg-[#4e4e4e]", red: "bg-[#ff4444]", orange: "bg-[#ff6e6e]", amber: "bg-[#ffa931]", blue: "bg-primary", green: "bg-[#81c784]", sky: "bg-[#64b5f6]" };

function Timeline({ data, shots }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>阶段</CardTitle>
        <span className="text-[13px] text-muted-foreground">按依赖顺序</span>
      </CardHeader>
      <ol>
        {data.nodes.map((node, index) => {
          const state = nodeState(node.tasks);
          const done = node.tasks.filter((task) => task.status === "succeeded").length;
          const cost = node.tasks.reduce((sum, task) => sum + (task.cost_yuan || 0), 0);
          return (
            <li key={node.id} className="flex gap-3 px-4 py-3">
              <div className="flex flex-col items-center pt-1">
                <span className={cn("size-2.5 rounded-full ring-4 ring-white", DOT[state.tone])} />
                {index < data.nodes.length - 1 ? <span className="mt-1 w-px flex-1 bg-border" /> : null}
              </div>
              <div className="min-w-0 flex-1 pb-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{node.title}</span>
                  <span className="text-xs text-muted-foreground">{kindLabel(node.kind)}</span>
                  <Badge tone={state.tone}>{state.label}</Badge>
                  <span className="flex-1" />
                  {node.tasks.length > 1 ? (
                    <span className="tnum text-xs text-muted-foreground">
                      {done}/{node.tasks.length}
                    </span>
                  ) : null}
                  {cost ? <Money value={cost} className="text-xs text-muted-foreground" /> : null}
                </div>
                {node.tasks.length > 1 ? <Progress value={done / node.tasks.length} className="mt-1.5 max-w-xs" tone={state.tone === "red" ? "red" : state.tone === "green" ? "green" : "blue"} /> : null}
                {node.kind !== "gate" && node.tasks.length ? (
                  <div className="mt-2 grid gap-2 sm:grid-cols-2 2xl:grid-cols-3">
                    {node.tasks.map((task) => (
                      <ItemCard key={task.id} task={task} run={data} title={typeof task.item_index === "number" && node.for_each ? shots[task.item_index]?.shot.data?.title : ""} />
                    ))}
                  </div>
                ) : node.kind === "gate" ? (
                  node.tasks.map((task) => <GateSummary key={task.id} task={task} />)
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">上游完成后展开</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function GateSummary({ task }) {
  const output = task.output || {};
  if (task.status === "waiting") {
    return (
      <a href="#gate" className="mt-1 inline-flex items-center gap-1 text-[13px] text-[#ffa931] hover:underline">
        <Clock className="size-3.5" />
        等待审批，见上方
      </a>
    );
  }
  if (task.status === "succeeded") {
    return (
      <p className="mt-1 text-[13px] text-muted-foreground">
        {output.auto ? "自动通过" : `${output.by || ""} 通过`}
        {task.finished_at ? (
          <>
            {" "}
            · <Time value={task.finished_at} />
          </>
        ) : null}
        {output.note ? ` · ${output.note}` : ""}
      </p>
    );
  }
  if (output.last_decision === "redo") {
    return (
      <p className="mt-1 text-[13px] text-muted-foreground">
        {output.by} 要求重做 {(output.redo || []).map((item) => itemLabel(item)).join("、")}
        {output.note ? `：${output.note}` : ""}，完成后再审
      </p>
    );
  }
  if (task.status === "failed") return <p className="mt-1 text-[13px] text-[#ff6e6e]">{task.error}</p>;
  return <p className="mt-1 text-[13px] text-muted-foreground">等上游完成</p>;
}

function QueuePosition({ task }) {
  const { can } = useSession();
  const detail = useQuery({
    queryKey: ["task", task.id, "position"],
    queryFn: () => api.get(`/api/tasks/${task.id}`),
    enabled: task.status === "ready" && can("queue:read"),
    staleTime: 10_000,
  });
  if (!detail.data?.queue_position) return null;
  return <span className="tnum text-xs text-[#64b5f6]">{task.pool} 队列第 {detail.data.queue_position} 位{detail.data.eta_seconds ? ` · 预计 ${duration(detail.data.eta_seconds)}` : " · 还没有同类历史耗时"}</span>;
}

function ItemCard({ task, run, title }) {
  const { can } = useSession();
  const confirm = useConfirm();
  const client = useQueryClient();
  const media = taskMedia(task);
  const active = ACTIVE_TASK.includes(task.status);
  const rerunnable = can("runs:create") && ["succeeded", "failed", "canceled", "needs_attention"].includes(task.status) && task.kind !== "gate" && run.status !== "canceled";
  const rerun = useMutation({
    mutationFn: () => api.post(`/api/runs/${run.id}/rerun`, { node: task.node_id, item: task.item || "" }),
    onSuccess: (result) => {
      toast.success("已安排重跑", `新建了 ${result.created.length} 个任务（含下游）`);
      client.invalidateQueries();
    },
  });
  const paid = ["image", "video", "tts", "music", "llm"].includes(task.kind);
  return (
    <div className={cn("rounded-md border bg-card p-2.5", task.status === "needs_attention" && "border-[#6a3a22] bg-[#3a2218]", task.status === "failed" && "border-[#6a2424] bg-[#3a1717]")}>
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
          {task.item !== "" ? itemLabel(task.item, task.item_index) : kindLabel(task.kind)}
          {title ? <span className="font-normal text-muted-foreground"> · {title}</span> : null}
        </span>
        <TaskStatus status={task.status} />
      </div>
      {active ? (
        <div className="mt-1.5 flex items-center gap-2">
          <Progress value={task.progress} />
          <span className="tnum text-xs text-muted-foreground">{Math.round((task.progress || 0) * 100)}%</span>
        </div>
      ) : null}
      {task.progress_message && active ? <p className="mt-1 truncate text-xs text-muted-foreground">{task.progress_message}</p> : null}
      {task.status === "ready" ? <QueuePosition task={task} /> : null}
      {task.attention ? <p className="mt-1 text-xs text-[#ffa931]">{task.attention}</p> : null}
      {task.status === "failed" && task.error ? <p className="mt-1 break-words text-xs text-[#ff6e6e]">{task.error}</p> : null}
      {task.output?.problems?.length ? <p className="mt-1 text-xs text-[#ffa931]">检查：{task.output.problems.join("，")}</p> : null}
      {task.kind === "check" && task.status === "succeeded" && task.output?.passed !== false ? <p className="mt-1 text-xs text-[#81c784]">检查通过</p> : null}
      {media.length ? (
        <div className={cn("mt-2 grid gap-1.5", media.length > 1 ? "grid-cols-2" : "grid-cols-1")}>
          {media.slice(0, 4).map((entry, index) => (
            <Thumb key={index} artifact={entry} label={entry.label} selected={entry.chosen && media.length > 1} />
          ))}
        </div>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {task.cost_yuan ? <Money value={task.cost_yuan} /> : null}
        {task.started_at ? <span className="tnum">{duration(elapsed(task.started_at, task.finished_at))}</span> : null}
        {task.provider ? <span className="truncate">{task.provider}</span> : null}
        {task.attempts > 1 ? <span className="tnum">第 {task.attempts} 次</span> : null}
        <span className="flex-1" />
        {media[0]?.url && task.kind !== "image" ? (
          <a className="text-primary hover:underline" href={downloadUrl(media[0].url)}>
            下载
          </a>
        ) : null}
        <Tooltip content={task.id}>
          <span className="font-mono text-[11px]">{shortId(task.id)}</span>
        </Tooltip>
      </div>
      {rerunnable || task.status === "needs_attention" ? (
        <div className="mt-2 flex flex-wrap gap-1.5 border-t pt-2">
          <TaskActions task={task} />
          {rerunnable ? (
            <Button
              size="xs"
              variant="ghost"
              onClick={() =>
                confirm({
                  title: `重跑${task.item !== "" ? itemLabel(task.item, task.item_index) : "这一步"}？`,
                  description: `会重新执行「${kindLabel(task.kind)}」${title ? `（${title}）` : ""}，并重跑依赖它的下游步骤。旧产物保留。`,
                  spends: paid ? true : undefined,
                  confirmText: "重跑",
                  action: () => rerun.mutateAsync(),
                })
              }
            >
              <RotateCcw />
              重跑这一条
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/* ---------- side cards ---------- */

function ArtifactThumb({ id }) {
  const info = useQuery({ queryKey: ["artifact", id], queryFn: () => api.get(`/api/artifacts/${id}`), staleTime: 30 * 60_000 });
  if (info.isLoading) return <Skeleton className="aspect-video w-full" />;
  if (info.isError) return <div className="flex aspect-video items-center justify-center rounded-md border text-xs text-muted-foreground">无法预览</div>;
  return <Thumb artifact={info.data} label={info.data.label} />;
}

function InputsCard({ data }) {
  const properties = data.spec?.inputs?.properties || {};
  return (
    <Card>
      <CardHeader>
        <CardTitle>输入</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {Object.entries(data.inputs || {}).map(([key, value]) => {
          const prop = properties[key] || {};
          const upload = prop.format === "asset-upload" || prop.items?.format === "asset-upload";
          return (
            <div key={key}>
              <p className="text-xs text-muted-foreground">{prop.title || key}</p>
              {upload ? (
                <div className="mt-1 grid grid-cols-3 gap-1.5">
                  {(Array.isArray(value) ? value : [value]).map((id) => (
                    <ArtifactThumb key={id} id={id} />
                  ))}
                </div>
              ) : Array.isArray(value) ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {value.map((item, index) => (
                    <span key={index} className="rounded bg-muted px-1.5 py-0.5 text-[13px]">
                      {String(item)}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="whitespace-pre-wrap break-words text-[13px]">{typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
              )}
            </div>
          );
        })}
        {!Object.keys(data.inputs || {}).length ? <p className="text-[13px] text-muted-foreground">没有输入</p> : null}
      </CardContent>
    </Card>
  );
}

function CostsCard({ data }) {
  const rows = data.costs || [];
  return (
    <Card>
      <CardHeader>
        <CardTitle>花费明细</CardTitle>
        <Money value={data.cost_actual} className="text-sm font-semibold" />
      </CardHeader>
      {rows.length ? (
        <Table>
          <THead>
            <tr>
              <th>供应商</th>
              <th>用量</th>
              <th className="text-right">金额</th>
            </tr>
          </THead>
          <TBody>
            {rows.map((row, index) => (
              <tr key={index}>
                <td className="text-[13px]">{row.provider}</td>
                <td className="tnum text-[13px] text-muted-foreground">
                  {row.quantity} {PRICING_UNIT[row.unit] || row.unit}
                </td>
                <td className="text-right text-[13px]">
                  <Money value={row.yuan} />
                </td>
              </tr>
            ))}
          </TBody>
        </Table>
      ) : (
        <CardContent>
          <p className="text-[13px] text-muted-foreground">还没有产生花费。</p>
        </CardContent>
      )}
    </Card>
  );
}
