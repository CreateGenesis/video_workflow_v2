import { Link, useNavigate, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Clapperboard, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Progress, TBody, THead, Table } from "@/components/ui/misc";
import { EmptyState, Money, PageHeader, QueryView, RunStatus, SkeletonRows, Time, useDocumentTitle } from "@/components/common";
import { api, qs } from "@/lib/api";
import { inputsSummary, shortId } from "@/lib/format";
import { RUN_MODE } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const STATUS_FILTERS = [
  { value: "", label: "全部" },
  { value: "running,waiting,paused", label: "未结束" },
  { value: "waiting", label: "等待处理" },
  { value: "succeeded", label: "已完成" },
  { value: "failed,canceled", label: "失败/取消" },
];

export default function RunsPage() {
  const { workspaceId, can } = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "";
  const workflow = params.get("workflow") || "";
  const mode = params.get("mode") || "";
  useDocumentTitle("运行");

  const workflows = useQuery({
    queryKey: ["workflows", workspaceId],
    queryFn: () => api.get(`/api/workflows${qs({ workspace_id: workspaceId })}`),
    enabled: Boolean(workspaceId) && can("workflows:read"),
  });
  const runs = useQuery({
    queryKey: ["runs", workspaceId, status, workflow, mode],
    queryFn: () => api.get(`/api/runs${qs({ workspace_id: workspaceId, status, workflow_id: workflow, mode, limit: 200 })}`),
    enabled: Boolean(workspaceId),
  });

  const update = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <div>
      <PageHeader
        title="运行"
        description="每次运行 = 一个已发布的工作流版本 + 一组输入。点开可以看阶段进度、审批闸门、下载成片。"
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
      <div className="mb-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="inline-flex max-w-full overflow-x-auto rounded-md border bg-card p-0.5">
          {STATUS_FILTERS.map((item) => (
            <button
              key={item.value}
              onClick={() => update("status", item.value)}
              className={cn("h-7 whitespace-nowrap rounded px-3 text-[13px] text-muted-foreground", status === item.value && "bg-accent font-medium text-accent-foreground")}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <Select
            className="w-full lg:w-56"
            value={workflow}
            onChange={(event) => update("workflow", event.target.value)}
            placeholder="全部工作流"
            options={(workflows.data?.items || []).map((item) => ({ value: item.id, label: item.name }))}
          />
          <Select
            className="w-36 shrink-0"
            value={mode}
            onChange={(event) => update("mode", event.target.value)}
            placeholder="全部类型"
            options={Object.entries(RUN_MODE).map(([value, meta]) => ({ value, label: meta.label }))}
          />
        </div>
      </div>
      <QueryView query={runs} skeleton={<SkeletonRows rows={6} />}>
        {(data) =>
          data.items.length ? (
            <Card className="overflow-hidden">
              <Table>
                <THead>
                  <tr>
                    <th>状态</th>
                    <th>工作流</th>
                    <th className="hidden md:table-cell">输入</th>
                    <th>进度</th>
                    <th className="text-right">估算 / 实际</th>
                    <th className="text-right">发起</th>
                  </tr>
                </THead>
                <TBody>
                  {data.items.map((run) => {
                    const ratio = run.progress.total ? run.progress.succeeded / run.progress.total : 0;
                    return (
                      <tr key={run.id} className="cursor-pointer" onClick={() => navigate(`/runs/${run.id}`)}>
                        <td>
                          <RunStatus status={run.status} />
                        </td>
                        <td className="min-w-40">
                          <Link to={`/runs/${run.id}`} className="font-medium hover:underline" onClick={(event) => event.stopPropagation()}>
                            {run.workflow_name}
                          </Link>
                          <span className="ml-1.5 text-xs text-muted-foreground">v{run.version}</span>
                          {run.mode !== "production" ? <span className="ml-1.5 text-xs text-[#b39ddb]">{RUN_MODE[run.mode]?.label}</span> : null}
                          {run.batch_id ? <span className="ml-1.5 text-xs text-muted-foreground">批量</span> : null}
                          <div className="font-mono text-[11px] text-muted-foreground">{shortId(run.id)}</div>
                        </td>
                        <td className="hidden max-w-80 truncate text-[13px] text-muted-foreground md:table-cell">{inputsSummary(run.inputs) || "—"}</td>
                        <td className="min-w-32">
                          <div className="flex items-center gap-2">
                            <Progress value={ratio} className="w-20" tone={run.status === "failed" ? "red" : run.status === "succeeded" ? "green" : "blue"} />
                            <span className="tnum text-xs text-muted-foreground">
                              {run.progress.succeeded}/{run.progress.total}
                            </span>
                          </div>
                          {run.progress.waiting ? <div className="mt-0.5 text-xs text-[#ffa931]">{run.progress.waiting} 项待处理</div> : null}
                        </td>
                        <td className="whitespace-nowrap text-right text-[13px]">
                          <Money value={run.cost_estimate || null} className="text-muted-foreground" /> / <Money value={run.cost_actual} />
                        </td>
                        <td className="whitespace-nowrap text-right text-[13px] text-muted-foreground">
                          <Time value={run.created_at} />
                        </td>
                      </tr>
                    );
                  })}
                </TBody>
              </Table>
            </Card>
          ) : (
            <EmptyState
              icon={Clapperboard}
              title={status || workflow || mode ? "没有符合条件的运行" : "还没有运行"}
              description={status || workflow || mode ? "换一个筛选条件试试。" : "选择一个已发布的工作流，填写灵感即可开始出片。"}
              action={
                can("runs:create") && !(status || workflow || mode) ? (
                  <Button asChild size="sm">
                    <Link to="/runs/new">发起运行</Link>
                  </Button>
                ) : null
              }
            />
          )
        }
      </QueryView>
    </div>
  );
}
