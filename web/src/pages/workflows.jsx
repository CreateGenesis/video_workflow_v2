import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FileJson, Play, Sparkles, Upload, Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { toast } from "@/components/ui/toast";
import { EmptyState, InlineError, Money, PageHeader, PageLoading, QueryView, Time, VersionStatus, useConfirm, useDocumentTitle } from "@/components/common";
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
  const [importing, setImporting] = useState(false);
  const actions = (
    <>
      {can("admin") ? <LoadSamplesButton workspaceId={workspaceId} /> : null}
      {can("workflows:draft") ? (
        <Button size="sm" onClick={() => setImporting(true)}>
          <Upload />
          导入 JSON
        </Button>
      ) : null}
    </>
  );
  return (
    <div>
      <PageHeader title="工作流" description="定型后的出片流程。agent 写草稿并试跑，审计员审过后发布；运行总是钉死某个已发布版本。" actions={actions} />
      {importing ? <ImportDialog workspaceId={workspaceId} onClose={() => setImporting(false)} /> : null}
      <QueryView query={list} skeleton={<PageLoading label="正在加载工作流" />}>
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
              description="三种方式：agent 定型后用 cvgen workflow draft <规格.json> 提交草稿；在这里导入一份 JSON；或者管理员先载入示例，改成你自己的供应商后发布。"
              action={<div className="flex flex-wrap justify-center gap-2">{actions}</div>}
            />
          )
        }
      </QueryView>
    </div>
  );
}

function LoadSamplesButton({ workspaceId }) {
  const client = useQueryClient();
  const confirm = useConfirm();
  const load = useMutation({
    mutationFn: () => api.post("/api/admin/samples", { workspace_id: workspaceId }),
    onSuccess: (result) => {
      const created = Object.values(result.workflows || {}).filter((item) => !item.skipped).length;
      toast.success(created ? `已载入 ${created} 个示例工作流` : "示例已经载入过", "示例是草稿；打开版本页把节点的供应商换成你已配置的实例，校验通过后即可发布");
      client.invalidateQueries({ queryKey: ["workflows"] });
      client.invalidateQueries({ queryKey: ["assets"] });
    },
    meta: { errorTitle: "载入示例失败" },
  });
  return (
    <Button
      size="sm"
      variant="outline"
      loading={load.isPending}
      onClick={() =>
        confirm({
          title: "载入示例工作流？",
          description: "会在当前工作区加入「小说片段-雪原-15秒」「产品广告-15秒」两个草稿，以及它们用到的风格、场景、参考图、提示模板等素材。不会花钱，可以重复执行。",
          confirmText: "载入",
          action: () => load.mutateAsync(),
        })
      }
    >
      <Sparkles />
      载入示例
    </Button>
  );
}

function ImportDialog({ workspaceId, onClose }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [notes, setNotes] = useState("");
  const [parseError, setParseError] = useState("");
  let parsed = null;
  try {
    parsed = text.trim() ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  const save = useMutation({
    mutationFn: (spec) => api.post("/api/workflows", { workspace_id: workspaceId, spec, notes }),
    onSuccess: (result) => {
      const errors = result.validation?.errors?.length || 0;
      if (errors) toast.error(`已存为草稿 v${result.version}，校验有 ${errors} 个问题`, "在版本页逐条修正后再发布");
      else toast.success(`已存为草稿 v${result.version}`, "校验通过，审计员可以发布");
      client.invalidateQueries({ queryKey: ["workflows"] });
      onClose();
      navigate(`/workflows/${result.workflow_id}/v/${result.version}`);
    },
    meta: { inline: true },
  });
  const readFile = async (file) => {
    if (!file) return;
    setText(await file.text());
    setParseError("");
  };
  const submit = (event) => {
    event.preventDefault();
    if (!text.trim()) return setParseError("先粘贴或选择一份工作流 JSON");
    if (!parsed) return setParseError("不是合法的 JSON，检查括号和引号");
    if (parsed.schema !== "cvgen.workflow/v1") return setParseError("schema 字段应为 cvgen.workflow/v1");
    setParseError("");
    save.mutate(parsed);
  };
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileJson className="size-4" />
            导入工作流
          </DialogTitle>
          <DialogDescription>同名工作流会追加一个新的草稿版本；不同名会新建工作流。导入后先校验，通过后由审计员发布。</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <form id="import-form" className="grid gap-4" onSubmit={submit}>
            <Field label="规格 JSON" htmlFor="wf-json" required error={parseError} hint={parsed?.name ? `工作流：${parsed.name}，${(parsed.nodes || []).length} 个步骤` : "格式见 docs/design/v2.md 第 4 节和示例"}>
              <Textarea id="wf-json" rows={14} className="font-mono text-xs" value={text} onChange={(event) => setText(event.target.value)} placeholder='{"schema": "cvgen.workflow/v1", "name": "…", "inputs": {…}, "nodes": […], "outputs": {…}, "budget": {…}}' />
            </Field>
            <label className="inline-flex w-fit cursor-pointer items-center gap-2 text-[13px] text-primary hover:underline">
              <Upload className="size-3.5" />
              从文件读取
              <input type="file" accept=".json,application/json" className="hidden" onChange={(event) => readFile(event.target.files?.[0])} />
            </label>
            <Field label="版本说明" htmlFor="wf-notes">
              <Input id="wf-notes" value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="这一版改了什么" />
            </Field>
          </form>
          {save.isError ? <InlineError className="mt-3">{save.error.message}</InlineError> : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" form="import-form" loading={save.isPending}>
            存为草稿
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
