import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, Clapperboard, Play, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton, TBody, THead, Table } from "@/components/ui/misc";
import { EmptyState, ErrorState, Money, PageHeader, RunStatus, SkeletonRows, Time, VersionStatus, useDocumentTitle } from "@/components/common";
import { api, qs } from "@/lib/api";
import { inputsSummary } from "@/lib/format";
import { RUN_MODE } from "@/lib/labels";
import { useSession } from "@/lib/session";

export function actorName(createdBy) {
  if (!createdBy) return "—";
  const parts = String(createdBy).split(":");
  return parts.length > 1 ? parts.slice(1).join(":") : createdBy;
}

export default function WorkflowPage() {
  const { id } = useParams();
  const { can } = useSession();
  const workflow = useQuery({ queryKey: ["workflow", id], queryFn: () => api.get(`/api/workflows/${id}`) });
  const runs = useQuery({
    queryKey: ["runs", "workflow", id],
    queryFn: () => api.get(`/api/runs${qs({ workflow_id: id, limit: 10 })}`),
    enabled: can("runs:read"),
  });
  const data = workflow.data;
  useDocumentTitle(data?.name || "工作流");

  if (workflow.isError) {
    return (
      <div>
        <PageHeader title="工作流" back={{ to: "/workflows", label: "工作流" }} />
        <ErrorState error={workflow.error} retry={workflow.refetch} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        back={{ to: "/workflows", label: "工作流" }}
        title={data ? data.name : <Skeleton className="h-7 w-48" />}
        meta={data?.published_version ? <span className="text-[13px] text-[#81c784]">已发布 v{data.published_version}</span> : null}
        description={data?.description}
        actions={
          data?.published_version && can("runs:create") ? (
            <Button asChild>
              <Link to={`/runs/new?workflow=${id}`}>
                <Play />
                发起运行
              </Link>
            </Button>
          ) : null
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>版本</CardTitle>
          <span className="text-[13px] text-muted-foreground">发布后的版本不可修改；运行钉死版本</span>
        </CardHeader>
        {workflow.isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={3} />
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <th>版本</th>
                <th>状态</th>
                <th>校验</th>
                <th className="hidden md:table-cell">说明</th>
                <th>创建</th>
                <th className="hidden sm:table-cell">发布</th>
                <th />
              </tr>
            </THead>
            <TBody>
              {data.versions.map((version) => (
                <tr key={version.version} className="cursor-pointer">
                  <td className="tnum font-medium">
                    <Link to={`/workflows/${id}/v/${version.version}`} className="hover:underline">
                      v{version.version}
                    </Link>
                  </td>
                  <td>
                    <VersionStatus status={version.status} />
                  </td>
                  <td className="whitespace-nowrap text-[13px]">
                    {version.errors ? (
                      <span className="inline-flex items-center gap-1 text-[#ff9c9c]">
                        <XCircle className="size-3.5" />
                        {version.errors} 个错误
                      </span>
                    ) : version.warnings ? (
                      <span className="inline-flex items-center gap-1 text-[#ffa931]">
                        <AlertTriangle className="size-3.5" />
                        {version.warnings} 条提示
                      </span>
                    ) : (
                      <span className="text-[#81c784]">通过</span>
                    )}
                  </td>
                  <td className="hidden max-w-72 truncate text-[13px] text-muted-foreground md:table-cell">{version.notes || "—"}</td>
                  <td className="whitespace-nowrap text-[13px]">
                    {actorName(version.created_by)} · <Time value={version.created_at} />
                  </td>
                  <td className="hidden whitespace-nowrap text-[13px] sm:table-cell">
                    {version.published_at ? (
                      <>
                        {version.published_by} · <Time value={version.published_at} />
                      </>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="text-right">
                    <Button asChild variant="ghost" size="xs">
                      <Link to={`/workflows/${id}/v/${version.version}`}>
                        查看
                        <ChevronRight />
                      </Link>
                    </Button>
                  </td>
                </tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      {can("runs:read") ? (
        <Card>
          <CardHeader>
            <CardTitle>最近的运行</CardTitle>
            <Button asChild variant="ghost" size="sm">
              <Link to={`/runs?workflow=${id}`}>全部</Link>
            </Button>
          </CardHeader>
          {runs.isLoading ? (
            <div className="p-4">
              <SkeletonRows rows={2} />
            </div>
          ) : runs.data?.items?.length ? (
            <div className="divide-y">
              {runs.data.items.map((run) => (
                <Link key={run.id} to={`/runs/${run.id}`} className="flex items-center gap-3 px-4 py-2.5 text-[13px] hover:bg-[#303030]">
                  <RunStatus status={run.status} />
                  <span className="tnum">v{run.version}</span>
                  {run.mode !== "production" ? <span className="text-[#b39ddb]">{RUN_MODE[run.mode]?.label}</span> : null}
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{inputsSummary(run.inputs) || run.id}</span>
                  <Money value={run.cost_actual} />
                  <Time value={run.created_at} className="w-16 text-right text-muted-foreground" />
                </Link>
              ))}
            </div>
          ) : (
            <div className="p-4">
              <EmptyState compact icon={Clapperboard} title="这个工作流还没有运行" description="发布后，制作人员可以填写灵感发起运行。" />
            </div>
          )}
        </Card>
      ) : null}
    </div>
  );
}
