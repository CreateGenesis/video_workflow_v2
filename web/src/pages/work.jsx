import { Suspense, lazy, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Clapperboard, FileText, ListChecks, MessageSquareText, Send, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import {
  Collapsible,
  CopyButton,
  EmptyState,
  ErrorState,
  InlineError,
  IdText,
  Money,
  PageHeader,
  QueryView,
  SkeletonCards,
  SkeletonRows,
  TaskStatus,
  Time,
  useDocumentTitle,
} from "@/components/common";
import { Thumb, VideoPlayer } from "@/components/media";
import { TaskRow, TaskDetailSheet } from "@/components/tasks";
import { api, qs } from "@/lib/api";
import { pretty, shortId } from "@/lib/format";
import { ACTOR_KIND, OPEN_TASK, actionLabel, kindLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { creatorLabel } from "@/pages/explore";

const WorkGraph = lazy(() => import("@/components/work-graph"));

export default function WorkPage() {
  const { workId } = useParams();
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "storyboard";
  const work = useQuery({ queryKey: ["work", workId], queryFn: () => api.get(`/api/works/${workId}`) });
  const info = work.data?.work;
  useDocumentTitle(info?.title || "作品");

  if (work.isError) {
    return (
      <div>
        <PageHeader title="作品" back={{ to: "/explore", label: "探索审计" }} />
        <ErrorState error={work.error} retry={work.refetch} />
      </div>
    );
  }

  const tasks = work.data?.tasks || [];
  const attention = tasks.filter((task) => task.status === "needs_attention" || task.status === "waiting").length;

  return (
    <div>
      <PageHeader
        back={{ to: "/explore", label: "探索审计" }}
        title={info ? info.title || "未命名作品" : <Skeleton className="h-7 w-56" />}
        meta={info ? <Badge tone={info.origin === "run" ? "gray" : "violet"}>{info.origin === "run" ? "运行生成" : "agent 探索"}</Badge> : null}
        description={
          info ? (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {info.brief ? <span>{info.brief}</span> : null}
              <span>
                由{creatorLabel(info.created_by)}创建于 <Time value={info.created_at} />
              </span>
              <IdText id={info.id} />
            </span>
          ) : null
        }
        actions={
          info?.run_id ? (
            <Button asChild variant="outline" size="sm">
              <Link to={`/runs/${info.run_id}`}>
                <Clapperboard />
                查看运行
              </Link>
            </Button>
          ) : null
        }
      />
      <Tabs value={tab} onValueChange={(value) => setParams(value === "storyboard" ? {} : { tab: value }, { replace: true })}>
        <TabsList>
          <TabsTrigger value="storyboard">分镜表</TabsTrigger>
          <TabsTrigger value="graph">关系图</TabsTrigger>
          {can("activity:read") ? <TabsTrigger value="activity">活动</TabsTrigger> : null}
          {can("notes:read") ? <TabsTrigger value="notes">审计意见</TabsTrigger> : null}
          <TabsTrigger value="tasks" count={attention || null}>
            任务
          </TabsTrigger>
        </TabsList>
        <TabsContent value="storyboard">
          <Storyboard workId={workId} />
        </TabsContent>
        <TabsContent value="graph">
          {!work.data && work.isLoading ? (
            <Skeleton className="h-[560px] w-full" />
          ) : (
            <Suspense fallback={<Skeleton className="h-[560px] w-full" />}>
              <WorkGraph workId={workId} snapshot={work.data} />
            </Suspense>
          )}
        </TabsContent>
        <TabsContent value="activity">
          <Activity workId={workId} />
        </TabsContent>
        <TabsContent value="notes">
          <Notes workId={workId} workspaceId={info?.workspace_id} />
        </TabsContent>
        <TabsContent value="tasks">
          <WorkTasks query={work} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/* ---------- storyboard ---------- */

function Storyboard({ workId }) {
  const board = useQuery({ queryKey: ["storyboard", workId], queryFn: () => api.get(`/api/works/${workId}/storyboard`) });
  return (
    <QueryView query={board} skeleton={<SkeletonCards count={2} className="sm:grid-cols-1 xl:grid-cols-1" />}>
      {(data) => {
        if (!data.shots.length) {
          return <EmptyState icon={FileText} title="这个作品还没有镜头" description="agent 新建 Shot 实体后，这里会按顺序列出每一镜的提示词、参考图、成片和花费。" />;
        }
        const total = data.shots.reduce((sum, row) => sum + (row.cost_yuan || 0), 0);
        return (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-muted-foreground">
              <span>
                共 <span className="tnum font-medium text-foreground">{data.shots.length}</span> 镜
              </span>
              <span>
                已成片 <span className="tnum font-medium text-foreground">{data.shots.filter((row) => row.clips.length).length}</span>
              </span>
              <span>
                镜头花费合计 <Money value={total} className="font-medium text-foreground" />
              </span>
            </div>
            {data.shots.map((row, index) => (
              <ShotCard key={row.shot.id} row={row} index={index} />
            ))}
          </div>
        );
      }}
    </QueryView>
  );
}

function PromptVersions({ shotId, count }) {
  const [open, setOpen] = useState(false);
  const versions = useQuery({
    queryKey: ["prompt-versions", shotId],
    queryFn: () => api.get(`/api/entities/${shotId}/prompt`),
    enabled: open,
  });
  return (
    <Collapsible title={count ? `提示词版本（${count}）` : "提示词版本"} extra={count ? <span className="text-xs font-normal text-muted-foreground">第 {count} 版为当前</span> : null}>
      <button type="button" className="mb-2 text-xs text-primary hover:underline" onClick={() => setOpen(true)}>
        {open ? "已加载" : "加载全部版本"}
      </button>
      {!versions.data && versions.isLoading ? <p className="text-xs text-muted-foreground">加载中…</p> : null}
      {versions.isError ? <InlineError>{versions.error.message}</InlineError> : null}
      {versions.data?.versions?.length ? (
        <ol className="space-y-2">
          {versions.data.versions.map((item, index) => (
            <li key={index} className="rounded-md border border-[#4e4e4e] bg-[#222] px-2.5 py-2 text-[13px]">
              <p className="mb-1 text-xs text-muted-foreground">
                第 {index + 1} 版 · <Time value={item.at} />
                {item.note ? ` · ${item.note}` : ""}
              </p>
              <p className="whitespace-pre-wrap text-[#ddd]">{item.text}</p>
            </li>
          ))}
        </ol>
      ) : open && versions.isSuccess ? (
        <p className="text-xs text-muted-foreground">还没有单独保存的版本，当前动作见上方。</p>
      ) : null}
    </Collapsible>
  );
}

function ShotCard({ row, index }) {
  const [openTask, setOpenTask] = useState(null);
  const shot = row.shot;
  const clip = row.clips[0];
  const title = shot.data?.title || `镜头 ${index + 1}`;
  const versions = shot.data?.prompt_versions?.length || 0;
  const checks = row.tasks.filter((task) => task.kind === "check" || task.kind === "inspect");
  return (
    <Card>
      {openTask ? <TaskDetailSheet taskId={openTask} onClose={() => setOpenTask(null)} /> : null}
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <span className="tnum flex size-6 items-center justify-center rounded bg-[#353535] text-xs font-semibold">{index + 1}</span>
        <span className="text-sm font-semibold">{title}</span>
        {row.duration ? <span className="tnum text-xs text-muted-foreground">{row.duration} 秒</span> : null}
        {versions > 1 ? <span className="text-xs text-muted-foreground">提示词第 {versions} 版</span> : null}
        {row.warnings.length ? (
          <Badge tone="amber">
            <AlertTriangle className="size-3" />
            {row.warnings.length} 条警告
          </Badge>
        ) : null}
        <span className="flex-1" />
        <span className="text-xs text-muted-foreground">
          花费 <Money value={row.cost_yuan} className="text-foreground" />
        </span>
      </div>
      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
        <div className="space-y-2">
          <VideoPlayer artifact={clip?.artifact} />
          {row.clips.length > 1 ? <p className="text-xs text-muted-foreground">共 {row.clips.length} 版成片，显示最新一版</p> : null}
        </div>
        <div className="min-w-0 space-y-3">
          {shot.data?.action ? <p className="text-[13px] leading-relaxed text-[#ddd]">{shot.data.action}</p> : null}
          {row.warnings.length ? (
            <ul className="space-y-1 rounded-md border border-[#6a4a18] bg-[#3a2a12] px-3 py-2 text-[13px] text-[#ffa931]">
              {row.warnings.map((warning, i) => (
                <li key={i} className="flex items-start gap-1.5">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                  {warning}
                </li>
              ))}
            </ul>
          ) : null}
          <Collapsible
            title="组合后的提示词"
            extra={row.prompt ? <span className="tnum text-xs font-normal text-muted-foreground">{row.prompt.length} 字</span> : null}
          >
            {row.prompt ? (
              <div className="space-y-2">
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-[13px] leading-relaxed text-[#ddd]" style={{ fontFamily: "inherit" }}>
                  {row.prompt}
                </pre>
                <CopyButton value={row.prompt} label="复制提示词" />
              </div>
            ) : (
              <p className="text-[13px] text-muted-foreground">组合失败，见上方警告。</p>
            )}
          </Collapsible>
          <PromptVersions shotId={shot.id} count={versions} />
          {checks.length ? (
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted-foreground">检查结果</p>
              <ul className="space-y-1 text-[13px]">
                {checks.map((task) => (
                  <li key={task.id} className="flex flex-wrap items-center gap-2">
                    <TaskStatus status={task.status} />
                    <span>{kindLabel(task.kind)}</span>
                    {task.output?.passed === false ? <span className="text-[#ffa931]">{(task.output.problems || []).join("，") || "未通过"}</span> : null}
                    {task.output?.passed === true || (task.kind === "check" && task.status === "succeeded" && task.output?.passed !== false) ? (
                      <span className="text-[#81c784]">通过</span>
                    ) : null}
                    {task.error ? <span className="text-[#ff6e6e]">{task.error}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {row.references.length ? (
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted-foreground">参考图</p>
              <div className="flex flex-wrap gap-2">
                {row.references.map((ref) => (
                  <div key={ref.id} className="w-28">
                    <Thumb artifact={ref.artifact} label={ref.role} />
                    <p className="mt-0.5 truncate text-xs text-muted-foreground" title={ref.title}>
                      {ref.title}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">没有参考图</p>
          )}
          {row.tasks.length ? (
            <div>
              <p className="mb-1.5 text-xs font-medium text-muted-foreground">任务</p>
              <div className="flex flex-wrap gap-1.5">
                {row.tasks.map((task) => (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => setOpenTask(task.id)}
                    title="查看任务详情"
                    className="inline-flex items-center gap-1.5 rounded-md border border-[#4e4e4e] bg-[#222] px-2 py-1 text-xs hover:border-primary hover:bg-[#2a2a2c]"
                  >
                    {kindLabel(task.kind)}
                    <TaskStatus status={task.status} />
                    {task.cost_yuan ? <Money value={task.cost_yuan} className="text-muted-foreground" /> : null}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

/* ---------- activity ---------- */

export function ActivityList({ workId, runId }) {
  const feed = useInfiniteQuery({
    queryKey: ["activity", workId || "", runId || ""],
    queryFn: ({ pageParam }) => api.get(`/api/activity${qs({ work_id: workId, run_id: runId, limit: 50, before: pageParam })}`),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.items.length === 50 ? last.next_before : undefined),
  });
  const [everything, setEverything] = useState(false);
  if (!feed.data && feed.isLoading) return <SkeletonRows rows={6} />;
  if (feed.isError) return <ErrorState error={feed.error} retry={feed.refetch} />;
  const all = feed.data.pages.flatMap((page) => page.items);
  if (!all.length) return <EmptyState compact icon={ListChecks} title="还没有活动" description="每一次写操作都会记一条，带上操作者。" />;
  const items = everything ? all : all.filter((event) => !isRoutine(event));
  const hidden = all.length - items.length;
  return (
    <Card>
      <div className="flex items-center justify-between gap-2 border-b px-4 py-2 text-xs text-muted-foreground">
        <span>{everything ? `全部 ${all.length} 条` : hidden ? `重点 ${items.length} 条，另有 ${hidden} 条执行器的例行记录` : `${items.length} 条`}</span>
        {hidden || everything ? (
          <Button variant="ghost" size="xs" onClick={() => setEverything((value) => !value)}>
            {everything ? "只看重点" : "显示全部"}
          </Button>
        ) : null}
      </div>
      <ol className="divide-y">
        {items.map((event) => (
          <li key={event.id} className="flex gap-3 px-4 py-2.5">
            <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", event.actor_kind === "user" ? "bg-primary" : event.actor_kind === "device" ? "bg-[#b39ddb]" : "bg-[#8a8a8a]")} />
            <div className="min-w-0 flex-1">
              <p className="text-[13px]">
                <span className="font-medium">{event.actor_name || event.actor_id}</span>
                <span className="text-muted-foreground">（{ACTOR_KIND[event.actor_kind] || event.actor_kind}）</span>
                <span className="ml-1">{actionLabel(event.action)}</span>
                {event.target_kind ? <span className="ml-1 text-muted-foreground">{event.target_kind}</span> : null}
                {event.target_id ? <IdText id={shortId(event.target_id)} className="ml-1" /> : null}
              </p>
              {event.payload && Object.keys(event.payload).length ? <PayloadLine payload={event.payload} /> : null}
            </div>
            <span className="shrink-0 text-xs text-muted-foreground">
              <Time value={event.ts} />
            </span>
          </li>
        ))}
      </ol>
      {feed.hasNextPage ? (
        <div className="border-t p-2 text-center">
          <Button variant="ghost" size="sm" onClick={() => feed.fetchNextPage()} loading={feed.isFetchingNextPage}>
            加载更早的活动
          </Button>
        </div>
      ) : null}
    </Card>
  );
}

const ROUTINE = new Set(["entity.create", "entity.update", "link.create", "task.create", "asset.version"]);

/** Bookkeeping by the executor or system (creating entities, links, tasks): hidden unless asked for. */
function isRoutine(event) {
  return ROUTINE.has(event.action) && (event.actor_kind === "worker" || event.actor_kind === "system");
}

function PayloadLine({ payload }) {
  const text = Object.entries(payload)
    .filter(([, value]) => value !== null && value !== "" && !(Array.isArray(value) && !value.length))
    .map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`)
    .join(" · ");
  if (!text) return null;
  return (
    <p className="mt-0.5 truncate text-xs text-muted-foreground" title={pretty(payload)}>
      {text}
    </p>
  );
}

function Activity({ workId }) {
  return <ActivityList workId={workId} />;
}

/* ---------- notes ---------- */

export function NotesPanel({ workId, runId, workspaceId }) {
  const { can } = useSession();
  const client = useQueryClient();
  const [showAll, setShowAll] = useState(false);
  const [text, setText] = useState("");
  const notes = useQuery({
    queryKey: ["notes", workId || "", runId || "", showAll],
    queryFn: () => api.get(`/api/notes${qs({ work_id: workId, run_id: runId, all: showAll ? "true" : "" })}`),
  });
  const add = useMutation({
    mutationFn: () => api.post("/api/notes", { workspace_id: workspaceId, work_id: workId || null, run_id: runId || null, text }),
    onSuccess: () => {
      setText("");
      toast.success("意见已发出", "agent 下次运行 cvgen review list 时会看到");
      client.invalidateQueries({ queryKey: ["notes"] });
    },
  });
  const resolve = useMutation({
    mutationFn: (id) => api.post(`/api/notes/${id}/resolve`),
    onSuccess: () => {
      toast.success("已关闭这条意见");
      client.invalidateQueries({ queryKey: ["notes"] });
    },
  });
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="order-2 space-y-3 lg:order-1">
        <div className="flex items-center justify-between">
          <p className="text-[13px] text-muted-foreground">{showAll ? "全部意见" : "未关闭的意见"}</p>
          <Button variant="ghost" size="xs" onClick={() => setShowAll((value) => !value)}>
            {showAll ? "只看未关闭" : "包括已关闭"}
          </Button>
        </div>
        <QueryView query={notes} skeleton={<SkeletonRows rows={3} />}>
          {(data) =>
            data.items.length ? (
              <div className="space-y-2">
                {data.items.map((note) => (
                  <Card key={note.id} className={cn("p-3.5", note.resolved && "bg-[#fafbfc]")}>
                    <div className="flex items-start gap-3">
                      <MessageSquareText className={cn("mt-0.5 size-4 shrink-0", note.resolved ? "text-muted-foreground" : "text-primary")} />
                      <div className="min-w-0 flex-1">
                        <p className={cn("whitespace-pre-wrap break-words text-sm", note.resolved && "text-muted-foreground")}>{note.text}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {note.author_name || "未知"} · <Time value={note.created_at} />
                          {note.resolved ? (
                            <span>
                              {" "}
                              · 已由 {String(note.resolved_by || "").split(":").pop()} 关闭
                            </span>
                          ) : null}
                        </p>
                      </div>
                      {!note.resolved ? (
                        <Button size="xs" variant="outline" onClick={() => resolve.mutate(note.id)} loading={resolve.isPending && resolve.variables === note.id}>
                          <Check />
                          关闭
                        </Button>
                      ) : null}
                    </div>
                  </Card>
                ))}
              </div>
            ) : (
              <EmptyState compact icon={MessageSquareText} title={showAll ? "还没有意见" : "没有未关闭的意见"} description="审计员写下的意见会交给 agent 读取（cvgen review list），agent 处理后关闭。" />
            )
          }
        </QueryView>
      </div>
      {can("notes:write") ? (
        <Card className="order-1 h-fit lg:order-2">
          <CardHeader>
            <CardTitle>给 agent 留意见</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Textarea
              rows={5}
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="例如：第 2 镜不要再出现血迹；参考图只锁纱布卷法。"
            />
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">agent 会在下一步操作前读取</span>
              <Button size="sm" onClick={() => add.mutate()} disabled={!text.trim() || !workspaceId} loading={add.isPending}>
                <Send />
                发出
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function Notes({ workId, workspaceId }) {
  return <NotesPanel workId={workId} workspaceId={workspaceId} />;
}

/* ---------- tasks ---------- */

function WorkTasks({ query }) {
  const [filter, setFilter] = useState("all");
  if (!query.data && query.isLoading) return <SkeletonRows rows={4} />;
  const tasks = query.data?.tasks || [];
  const shown = tasks.filter((task) =>
    filter === "attention" ? ["needs_attention", "waiting"].includes(task.status) : filter === "open" ? OPEN_TASK.includes(task.status) : true,
  );
  const filters = [
    ["all", `全部 ${tasks.length}`],
    ["open", `未结束 ${tasks.filter((task) => OPEN_TASK.includes(task.status)).length}`],
    ["attention", `需要处理 ${tasks.filter((task) => ["needs_attention", "waiting"].includes(task.status)).length}`],
  ];
  return (
    <div className="space-y-3">
      <div className="inline-flex rounded-md border bg-card p-0.5">
        {filters.map(([value, label]) => (
          <button key={value} onClick={() => setFilter(value)} className={cn("tnum h-7 rounded px-3 text-[13px] text-muted-foreground", filter === value && "bg-accent font-medium text-accent-foreground")}>
            {label}
          </button>
        ))}
      </div>
      {shown.length ? (
        <Card className="divide-y">
          {shown.map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
        </Card>
      ) : (
        <EmptyState compact icon={Workflow} title="没有符合条件的任务" description="agent 发起的生成、检查、剪辑任务都会列在这里。" />
      )}
    </div>
  );
}
