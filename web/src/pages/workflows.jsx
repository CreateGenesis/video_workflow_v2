import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Play, Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, Money, PageHeader, QueryView, SkeletonCards, Time, VersionStatus, useDocumentTitle } from "@/components/common";
import { api, qs } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function WorkflowsPage() {
  const { workspaceId, can } = useSession();
  useDocumentTitle("工作流");
  const list = useQuery({
    queryKey: ["workflows", workspaceId],
    queryFn: () => api.get(`/api/workflows${qs({ workspace_id: workspaceId })}`),
    enabled: Boolean(workspaceId),
  });
  return (
    <div>
      <PageHeader title="工作流" description="定型后的出片流程。agent 写草稿并试跑，审计员审过后发布；运行总是钉死某个已发布版本。" />
      <QueryView query={list} skeleton={<SkeletonCards count={4} className="xl:grid-cols-2" />}>
        {(data) =>
          data.items.length ? (
            <div className="grid gap-3 xl:grid-cols-2">
              {data.items.map((workflow) => {
                const latest = workflow.versions[0];
                const drafts = workflow.versions.filter((version) => version.status === "draft").length;
                return (
                  <Card key={workflow.id} className="flex flex-col">
                    <Link to={`/workflows/${workflow.id}`} className="group flex-1 p-4 hover:bg-[#303030]">
                      <div className="flex items-start gap-3">
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                          <Workflow className="size-4.5" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-[15px] font-semibold">{workflow.name}</span>
                            {workflow.published_version ? (
                              <span className="text-xs text-[#81c784]">已发布 v{workflow.published_version}</span>
                            ) : (
                              <span className="text-xs text-muted-foreground">未发布</span>
                            )}
                            {drafts ? <span className="text-xs text-muted-foreground">· {drafts} 个草稿</span> : null}
                          </div>
                          {workflow.description ? <p className="mt-1 line-clamp-2 text-[13px] text-muted-foreground">{workflow.description}</p> : null}
                        </div>
                        <ChevronRight className="size-4 text-muted-foreground group-hover:text-foreground" />
                      </div>
                    </Link>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-4 py-2.5 text-xs text-muted-foreground">
                      {latest ? (
                        <span className="flex items-center gap-1.5">
                          最新 v{latest.version} <VersionStatus status={latest.status} />
                        </span>
                      ) : null}
                      <span className="tnum">生产运行 {workflow.runs} 次</span>
                      <span>
                        平均花费 <Money value={workflow.avg_cost_yuan} className="text-foreground" />
                      </span>
                      {latest ? (
                        <span>
                          更新于 <Time value={latest.created_at} />
                        </span>
                      ) : null}
                      <span className="flex-1" />
                      {workflow.published_version && can("runs:create") ? (
                        <Button asChild size="xs">
                          <Link to={`/runs/new?workflow=${workflow.id}`}>
                            <Play />
                            发起运行
                          </Link>
                        </Button>
                      ) : null}
                    </div>
                  </Card>
                );
              })}
            </div>
          ) : (
            <EmptyState
              icon={Workflow}
              title="还没有工作流"
              description="agent 在探索期定型后，用 cvgen workflow draft save 提交草稿，审计员在这里审核并发布。"
            />
          )
        }
      </QueryView>
    </div>
  );
}
