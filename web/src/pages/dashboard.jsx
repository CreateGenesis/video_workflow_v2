import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BellRing, CalendarDays, CheckCircle2, Clapperboard, Coins, Plus, Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/misc";
import { EmptyState, ErrorState, Money, PageHeader, RunStatus, SkeletonRows, StatCard, Time, useDocumentTitle } from "@/components/common";
import { GettingStarted } from "@/components/getting-started";
import { TaskRow } from "@/components/tasks";
import { api, qs } from "@/lib/api";
import { duration, yuan } from "@/lib/format";
import { RUN_MODE, TERMINAL_RUN } from "@/lib/labels";
import { useSession } from "@/lib/session";

function sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export default function Dashboard() {
  const { me, can, workspaceId } = useSession();
  useDocumentTitle("工作台");

  const attention = useQuery({
    queryKey: ["tasks", "attention", workspaceId],
    queryFn: () => api.get("/api/tasks?status=needs_attention,waiting&limit=50"),
    enabled: can("queue:read"),
  });
  const runs = useQuery({
    queryKey: ["runs", "recent", workspaceId],
    queryFn: () => api.get(`/api/runs${qs({ workspace_id: workspaceId, limit: 8 })}`),
    enabled: can("runs:read") && Boolean(workspaceId),
  });
  const pools = useQuery({
    queryKey: ["pools"],
    queryFn: () => api.get("/api/admin/pools"),
    enabled: can("queue:read"),
  });
  const costs = useQuery({
    queryKey: ["costs", "day", workspaceId],
    queryFn: () => api.get(`/api/costs${qs({ group: "day", days: 31, workspace_id: workspaceId })}`),
    enabled: can("costs:read") && Boolean(workspaceId),
  });

  const now = new Date();
  const costItems = costs.data?.items || [];
  const today = costItems.filter((item) => sameDay(new Date(item.key), now)).reduce((sum, item) => sum + (item.yuan || 0), 0);
  const month = costItems
    .filter((item) => {
      const date = new Date(item.key);
      return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth();
    })
    .reduce((sum, item) => sum + (item.yuan || 0), 0);
  const attentionItems = attention.data?.items || [];
  const activeRuns = (runs.data?.items || []).filter((run) => !TERMINAL_RUN.includes(run.status)).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title={`你好，${me.name}`}
        description="这里汇总了等你处理的事项、最近的运行、队列和花费。"
        actions={
          can("runs:create") ? (
            <Button asChild>
              <Link to="/runs/new">
                <Plus />
                发起运行
              </Link>
            </Button>
          ) : null
        }
      />

      <GettingStarted />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="等我处理" value={can("queue:read") ? attentionItems.length : "—"} hint="闸门审批与异常任务" icon={BellRing} tone="amber" to="/queue" />
        <StatCard label="进行中的运行" value={can("runs:read") ? activeRuns : "—"} hint="最近 8 条中" icon={Clapperboard} tone="blue" to="/runs?status=running,waiting,paused" />
        <StatCard label="今日花费" value={costs.isLoading ? "…" : yuan(today, { digits: 2 })} hint="本工作区，按入账时间" icon={Wallet} />
        <StatCard label="本月花费" value={costs.isLoading ? "…" : yuan(month, { digits: 2 })} hint={`${now.getMonth() + 1} 月累计`} icon={CalendarDays} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-5">
          {can("queue:read") ? (
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>等我处理</CardTitle>
                  <p className="text-[13px] text-muted-foreground">待审批的闸门、需要人工处理的任务</p>
                </div>
                <Button asChild variant="ghost" size="sm">
                  <Link to="/queue">
                    队列
                    <ArrowRight />
                  </Link>
                </Button>
              </CardHeader>
              {attention.isLoading ? (
                <CardContent>
                  <SkeletonRows rows={2} />
                </CardContent>
              ) : attention.isError ? (
                <CardContent>
                  <ErrorState error={attention.error} retry={attention.refetch} />
                </CardContent>
              ) : attentionItems.length ? (
                <div className="divide-y">
                  {attentionItems.slice(0, 6).map((task) => (
                    <TaskRow key={task.id} task={task} showContext compact />
                  ))}
                </div>
              ) : (
                <CardContent>
                  <EmptyState compact icon={CheckCircle2} title="没有待处理的事项" description="闸门等待审批或任务出现异常时，会出现在这里。" />
                </CardContent>
              )}
            </Card>
          ) : null}

          {can("runs:read") ? (
            <Card>
              <CardHeader>
                <CardTitle>最近的运行</CardTitle>
                <Button asChild variant="ghost" size="sm">
                  <Link to="/runs">
                    全部运行
                    <ArrowRight />
                  </Link>
                </Button>
              </CardHeader>
              {runs.isLoading ? (
                <CardContent>
                  <SkeletonRows rows={3} />
                </CardContent>
              ) : runs.isError ? (
                <CardContent>
                  <ErrorState error={runs.error} retry={runs.refetch} />
                </CardContent>
              ) : runs.data?.items?.length ? (
                <div className="divide-y">
                  {runs.data.items.map((run) => (
                    <Link key={run.id} to={`/runs/${run.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-[#303030]">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-sm font-medium">{run.workflow_name}</span>
                          <span className="text-xs text-muted-foreground">v{run.version}</span>
                          {run.mode !== "production" ? <span className="text-xs text-[#b39ddb]">{RUN_MODE[run.mode]?.label}</span> : null}
                        </div>
                        <div className="mt-1 flex items-center gap-2">
                          <Progress value={run.progress.total ? run.progress.succeeded / run.progress.total : 0} className="max-w-40" tone={run.status === "failed" ? "red" : run.status === "succeeded" ? "green" : "blue"} />
                          <span className="tnum text-xs text-muted-foreground">
                            {run.progress.succeeded}/{run.progress.total}
                          </span>
                        </div>
                      </div>
                      <div className="hidden text-right text-xs text-muted-foreground sm:block">
                        <Money value={run.cost_actual} className="block text-[13px] text-foreground" />
                        <Time value={run.created_at} />
                      </div>
                      <RunStatus status={run.status} />
                    </Link>
                  ))}
                </div>
              ) : (
                <CardContent>
                  <EmptyState
                    compact
                    icon={Clapperboard}
                    title="还没有运行"
                    description="选择一个已发布的工作流，填写灵感即可开始出片。"
                    action={
                      can("runs:create") ? (
                        <Button asChild size="sm">
                          <Link to="/runs/new">发起第一个运行</Link>
                        </Button>
                      ) : null
                    }
                  />
                </CardContent>
              )}
            </Card>
          ) : null}
        </div>

        <div className="space-y-5">
          {can("queue:read") ? (
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>资源池</CardTitle>
                  <p className="text-[13px] text-muted-foreground">占用 / 并发上限 · 排队数</p>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {pools.isLoading ? (
                  <SkeletonRows rows={4} />
                ) : pools.isError ? (
                  <ErrorState error={pools.error} retry={pools.refetch} />
                ) : (
                  (pools.data?.items || [])
                    .filter((pool) => pool.name !== "gate")
                    .map((pool) => (
                      <div key={pool.name} className="space-y-1">
                        <div className="flex items-center justify-between text-[13px]">
                          <span className="font-medium">
                            {pool.name}
                            {pool.paused ? <span className="ml-1.5 text-xs font-normal text-[#b39ddb]">已暂停</span> : null}
                          </span>
                          <span className="tnum text-muted-foreground">
                            {pool.busy}/{pool.concurrency}
                            {pool.ready ? <span className="ml-2 text-[#64b5f6]">排队 {pool.ready}{pool.eta_seconds ? ` · 预计 ${duration(pool.eta_seconds)}` : " · 暂无历史"}</span> : null}
                          </span>
                        </div>
                        <Progress value={pool.concurrency ? pool.busy / pool.concurrency : 0} tone={pool.paused ? "gray" : "blue"} />
                      </div>
                    ))
                )}
              </CardContent>
            </Card>
          ) : null}

          {can("costs:read") ? (
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>近 7 天花费</CardTitle>
                  <p className="text-[13px] text-muted-foreground">按天汇总，含探索与生产</p>
                </div>
                <Coins className="size-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                {costs.isLoading ? (
                  <SkeletonRows rows={3} />
                ) : costs.isError ? (
                  <ErrorState error={costs.error} retry={costs.refetch} />
                ) : (
                  <CostDays items={costItems} />
                )}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function CostDays({ items }) {
  const days = [];
  const now = new Date();
  for (let offset = 0; offset < 7; offset += 1) {
    const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() - offset);
    const total = items.filter((item) => sameDay(new Date(item.key), date)).reduce((sum, item) => sum + (item.yuan || 0), 0);
    days.push({ date, total });
  }
  const max = Math.max(...days.map((day) => day.total), 0);
  if (!max) return <p className="py-4 text-center text-[13px] text-muted-foreground">最近 7 天没有花费记录。</p>;
  return (
    <div className="space-y-1.5">
      {days.map((day) => (
        <div key={day.date.toISOString()} className="grid grid-cols-[3.5rem_1fr_4.5rem] items-center gap-2 text-[13px]">
          <span className="tnum text-muted-foreground">
            {day.date.getMonth() + 1}/{day.date.getDate()}
          </span>
          <div className="h-2 overflow-hidden rounded-sm bg-[#353535]">
            <div className="h-full rounded-sm bg-primary/80" style={{ width: `${(day.total / max) * 100}%` }} />
          </div>
          <Money value={day.total} digits={2} className="text-right" />
        </div>
      ))}
    </div>
  );
}
