import { useState } from "react";
import { useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Boxes, FileCode2, FileText, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Collapsible, CopyButton, EmptyState, JsonView, PageHeader, QueryView, SkeletonCards, SkeletonRows, Time, useDocumentTitle } from "@/components/common";
import { MediaMeta, Thumb } from "@/components/media";
import { api, qs } from "@/lib/api";
import { ASSET_KIND } from "@/lib/labels";
import { useOntology, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

function useKindLabel() {
  const ontology = useOntology();
  return (kind) => ontology.data?.types?.[kind]?.label || ASSET_KIND[kind] || kind;
}

function preview(item) {
  const data = item.data || {};
  if (item.kind === "prompt") return data.text;
  if (item.kind === "schema") return data.title || data.description || "JSON Schema";
  if (item.kind === "comfy_template") return `节点 ${Object.keys(data.graph || {}).length} 个 · 绑定 ${Object.keys(data.bindings || {}).join("、")}`;
  return Object.entries(data)
    .filter(([key, value]) => key !== "title" && typeof value === "string" && value)
    .map(([, value]) => value)
    .join("；");
}

export default function LibraryPage() {
  const { workspaceId } = useSession();
  const kindLabel = useKindLabel();
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") || "";
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(null);
  useDocumentTitle("素材库");
  const assets = useQuery({
    queryKey: ["assets", workspaceId],
    queryFn: () => api.get(`/api/assets${qs({ workspace_id: workspaceId })}`),
    enabled: Boolean(workspaceId),
  });
  const items = assets.data?.items || [];
  const counts = items.reduce((map, item) => ({ ...map, [item.kind]: (map[item.kind] || 0) + 1 }), {});
  const shown = items.filter(
    (item) => (!kind || item.kind === kind) && (!search || `${item.title} ${item.name}`.toLowerCase().includes(search.trim().toLowerCase())),
  );

  return (
    <div>
      <PageHeader title="素材库" description="工作区级、带版本的可复用素材：本体实体、提示模板、输出 schema、ComfyUI 模板和媒体。工作流按版本引用。" />
      <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setParams({}, { replace: true })}
            className={cn("h-7 rounded-md border bg-card px-2.5 text-[13px] text-muted-foreground", !kind && "border-primary/40 bg-accent font-medium text-accent-foreground")}
          >
            全部 <span className="tnum">{items.length}</span>
          </button>
          {Object.entries(counts).map(([value, count]) => (
            <button
              key={value}
              onClick={() => setParams({ kind: value }, { replace: true })}
              className={cn("h-7 rounded-md border bg-card px-2.5 text-[13px] text-muted-foreground", kind === value && "border-primary/40 bg-accent font-medium text-accent-foreground")}
            >
              {kindLabel(value)} <span className="tnum">{count}</span>
            </button>
          ))}
        </div>
        <div className="relative lg:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-8" placeholder="按名称筛选" value={search} onChange={(event) => setSearch(event.target.value)} />
        </div>
      </div>
      <QueryView query={assets} skeleton={<SkeletonCards count={6} />}>
        {() =>
          !items.length ? (
            <EmptyState icon={Boxes} title="素材库是空的" description="agent 可以用 cvgen asset promote 把作品里定型的实体提升为素材，供工作流按版本引用。" />
          ) : !shown.length ? (
            <EmptyState compact icon={Search} title="没有匹配的素材" description="换个类型或关键词试试。" />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {shown.map((item) => (
                <Card key={item.id} className="flex flex-col overflow-hidden">
                  <button className="flex flex-1 flex-col text-left hover:bg-[#303030]" onClick={() => setOpen(item)}>
                    {item.artifact ? (
                      <div className="pointer-events-none border-b">
                        <Thumb artifact={item.artifact} className="rounded-none border-0" />
                      </div>
                    ) : null}
                    <div className="flex-1 p-3.5">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate text-sm font-semibold">{item.title || item.name}</span>
                        <Badge tone={ASSET_KIND[item.kind] ? "gray" : "violet"}>{kindLabel(item.kind)}</Badge>
                      </div>
                      <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{item.ref}</p>
                      {!item.artifact ? <p className="mt-2 line-clamp-3 text-[13px] text-[#ccc]">{preview(item) || "—"}</p> : null}
                    </div>
                  </button>
                  <div className="flex items-center justify-between border-t px-3.5 py-2 text-xs text-muted-foreground">
                    <span className="tnum">最新 v{item.latest}</span>
                    <Time value={item.created_at} />
                  </div>
                </Card>
              ))}
            </div>
          )
        }
      </QueryView>
      {open ? <AssetDialog item={open} workspaceId={workspaceId} kindLabel={kindLabel} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}

function AssetDialog({ item, workspaceId, kindLabel, onClose }) {
  const detail = useQuery({
    queryKey: ["asset", workspaceId, item.name],
    queryFn: () => api.get(`/api/assets/${workspaceId}/${encodeURIComponent(item.name)}`),
  });
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {item.kind === "prompt" ? <FileText className="size-4" /> : item.kind === "schema" || item.kind === "comfy_template" ? <FileCode2 className="size-4" /> : null}
            {item.title || item.name}
            <Badge>{kindLabel(item.kind)}</Badge>
          </DialogTitle>
          <DialogDescription className="flex items-center gap-2">
            <code>{item.ref}</code>
            <CopyButton value={item.ref} label="复制引用" />
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-2">
          {detail.isLoading ? (
            <SkeletonRows rows={2} />
          ) : (
            (detail.data?.versions || []).map((version, index) => (
              <Collapsible
                key={version.version}
                defaultOpen={index === 0}
                title={`v${version.version}${version.note ? ` · ${version.note}` : ""}`}
                extra={
                  <span className="text-xs font-normal text-muted-foreground">
                    {String(version.created_by || "").split(":").pop()} · <Time value={version.created_at} />
                  </span>
                }
              >
                <div className="space-y-2">
                  {version.artifact ? (
                    <div className="max-w-sm">
                      <Thumb artifact={version.artifact} />
                      <MediaMeta artifact={version.artifact} className="mt-1" />
                    </div>
                  ) : null}
                  {item.kind === "prompt" && version.data?.text ? (
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border bg-[#222] p-3 text-[13px] leading-relaxed" style={{ fontFamily: "inherit" }}>
                      {version.data.text}
                    </pre>
                  ) : (
                    <JsonView value={version.data} maxHeight="20rem" />
                  )}
                </div>
              </Collapsible>
            ))
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
