import { Link, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Search, Telescope } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, PageHeader, QueryView, SkeletonRows, Time, useDocumentTitle } from "@/components/common";
import { api, qs } from "@/lib/api";
import { ACTOR_KIND } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const ORIGINS = [
  { value: "explore", label: "agent 探索" },
  { value: "run", label: "运行生成" },
  { value: "", label: "全部" },
];

export function creatorLabel(createdBy) {
  if (!createdBy) return "—";
  const [kind] = String(createdBy).split(":");
  return ACTOR_KIND[kind] || kind;
}

export default function ExplorePage() {
  const { workspaceId } = useSession();
  const [params, setParams] = useSearchParams();
  const origin = params.get("origin") ?? "explore";
  const [search, setSearch] = useState("");
  useDocumentTitle("探索审计");
  const works = useQuery({
    queryKey: ["works", workspaceId, origin],
    queryFn: () => api.get(`/api/works${qs({ workspace_id: workspaceId, origin })}`),
    enabled: Boolean(workspaceId),
  });

  return (
    <div>
      <PageHeader title="探索审计" description="agent 在探索期搭建的作品。打开作品可以看分镜表、关系图、活动流，并给 agent 留审计意见。" />
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex rounded-md border bg-card p-0.5">
          {ORIGINS.map((item) => (
            <button
              key={item.value}
              onClick={() => setParams(item.value === "explore" ? {} : { origin: item.value })}
              className={cn("h-7 rounded px-3 text-[13px] text-muted-foreground", origin === item.value && "bg-accent font-medium text-accent-foreground")}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="relative sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="按标题筛选" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      </div>
      <QueryView query={works} skeleton={<SkeletonRows rows={5} />}>
        {(data) => {
          const items = data.items.filter((item) => !search || (item.title || "").includes(search.trim()));
          if (!data.items.length) {
            return (
              <EmptyState
                icon={Telescope}
                title={origin === "explore" ? "还没有探索作品" : "没有作品"}
                description="agent 通过 cvgen work new 创建作品后会出现在这里。先在「设置 → 工具下载」下载 cvgen，并用 cvgen login 批准设备。"
              />
            );
          }
          if (!items.length) return <EmptyState compact icon={Search} title="没有匹配的作品" description="换个关键词试试。" />;
          return (
            <Card className="divide-y overflow-hidden">
              {items.map((work) => (
                <Link key={work.id} to={`/explore/${work.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-[#303030]">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium">{work.title || "未命名作品"}</span>
                      <Badge tone={work.origin === "run" ? "gray" : "violet"}>{work.origin === "run" ? "运行" : "探索"}</Badge>
                      {work.kind && work.kind !== "运行" ? <span className="text-xs text-muted-foreground">{work.kind}</span> : null}
                    </div>
                    {work.brief ? <p className="mt-0.5 line-clamp-1 text-[13px] text-muted-foreground">{work.brief}</p> : null}
                  </div>
                  <div className="hidden w-24 text-right text-[13px] sm:block">
                    <span className="tnum">{work.entities}</span>
                    <span className="text-muted-foreground"> 个实体</span>
                  </div>
                  <div className="hidden w-24 text-right text-[13px] text-muted-foreground md:block">{creatorLabel(work.created_by)}</div>
                  <div className="w-20 text-right text-[13px] text-muted-foreground">
                    <Time value={work.created_at} />
                  </div>
                  <ChevronRight className="size-4 text-muted-foreground" />
                </Link>
              ))}
            </Card>
          );
        }}
      </QueryView>
    </div>
  );
}
