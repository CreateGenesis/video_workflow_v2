import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArchiveX, CheckCircle2, Code2, FlaskConical, GitCompare, Play, Rocket, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import {
  Collapsible,
  EmptyState,
  ErrorState,
  InlineError,
  JsonView,
  KeyValues,
  Money,
  Notice,
  PageHeader,
  SkeletonRows,
  Time,
  VersionStatus,
  useConfirm,
  useDocumentTitle,
} from "@/components/common";
import { CompileResult } from "@/components/compile-result";
import { KindIcon, StepGraph } from "@/components/step-graph";
import { slotColor } from "@/lib/comfy";
import { SchemaForm, initialValues, toInputs, validate } from "@/components/schema-form";
import { api } from "@/lib/api";
import { ROLE, kindLabel } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { actorName } from "@/pages/workflow";

export default function WorkflowVersionPage() {
  const { id, version } = useParams();
  const { can } = useSession();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "overview";
  const workflow = useQuery({ queryKey: ["workflow", id], queryFn: () => api.get(`/api/workflows/${id}`) });
  const detail = useQuery({ queryKey: ["workflow-version", id, version], queryFn: () => api.get(`/api/workflows/${id}/versions/${version}`) });
  const data = detail.data;
  const name = workflow.data?.name;
  useDocumentTitle(name ? `${name} v${version}` : "工作流版本");

  if (detail.isError) {
    return (
      <div>
        <PageHeader title={`版本 v${version}`} back={{ to: `/workflows/${id}`, label: name || "工作流" }} />
        <ErrorState error={detail.error} retry={detail.refetch} />
      </div>
    );
  }

  const versions = workflow.data?.versions || [];
  const previous = versions.filter((item) => item.version < Number(version)).map((item) => item.version)[0];

  return (
    <div>
      <PageHeader
        back={{ to: `/workflows/${id}`, label: name || "工作流" }}
        title={
          <span className="flex items-center gap-2">
            {name || <Skeleton className="inline-block h-6 w-40" />}
            <span className="tnum text-muted-foreground">v{version}</span>
          </span>
        }
        meta={data ? <VersionStatus status={data.status} /> : null}
        description={
          data ? (
            <span>
              {actorName(data.created_by)} 创建于 <Time value={data.created_at} />
              {data.published_at ? (
                <>
                  {" "}
                  · {data.published_by} 发布于 <Time value={data.published_at} />
                </>
              ) : null}
              {data.notes ? ` · ${data.notes}` : ""}
            </span>
          ) : null
        }
        actions={data ? <VersionActions id={id} version={version} data={data} name={name} /> : null}
      />
      {!data && detail.isLoading ? (
        <SkeletonRows rows={6} />
      ) : (
        <Tabs value={tab} onValueChange={(value) => setParams(value === "overview" ? {} : { tab: value }, { replace: true })}>
          <TabsList>
            <TabsTrigger value="overview">概览与步骤</TabsTrigger>
            <TabsTrigger value="spec">规格 JSON</TabsTrigger>
            <TabsTrigger value="diff">与上一版的差异</TabsTrigger>
            <TabsTrigger value="compile">预览提示词</TabsTrigger>
          </TabsList>
          <TabsContent value="overview">
            <Overview data={data} />
          </TabsContent>
          <TabsContent value="spec">
            <SpecView spec={data.spec} fixtures={data.fixtures} />
          </TabsContent>
          <TabsContent value="diff">
            <DiffView id={id} version={Number(version)} versions={versions} previous={previous} />
          </TabsContent>
          <TabsContent value="compile">
            <CompileForm id={id} version={version} data={data} canRun={can("runs:create")} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

function VersionActions({ id, version, data, name }) {
  const { can } = useSession();
  const confirm = useConfirm();
  const client = useQueryClient();
  const errors = data.validation?.errors?.length || 0;
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["workflow", id] });
    client.invalidateQueries({ queryKey: ["workflow-version", id, version] });
    client.invalidateQueries({ queryKey: ["workflows"] });
  };
  const publish = useMutation({
    mutationFn: () => api.post(`/api/workflows/${id}/versions/${version}/publish`),
    onSuccess: () => {
      toast.success(`已发布 v${version}`, "制作人员现在可以用这个版本发起运行");
      refresh();
    },
  });
  const retire = useMutation({
    mutationFn: () => api.post(`/api/workflows/${id}/versions/${version}/retire`),
    onSuccess: () => {
      toast.success(`已下线 v${version}`);
      refresh();
    },
  });
  return (
    <>
      {data.status === "published" && can("runs:create") ? (
        <Button asChild variant="outline">
          <Link to={`/runs/new?workflow=${id}`}>
            <Play />
            发起运行
          </Link>
        </Button>
      ) : null}
      {can("workflows:publish") && data.status === "draft" ? (
        <Button
          disabled={errors > 0}
          title={errors ? "校验没有通过，不能发布" : undefined}
          onClick={() =>
            confirm({
              title: `发布 ${name} v${version}？`,
              description: `发布后这个版本不可再修改，制作人员和 API 调用方会用它发起运行（花费由运行产生）。\n${
                data.validation?.warnings?.length ? `有 ${data.validation.warnings.length} 条提示，请确认已经看过。` : ""
              }`,
              confirmText: "确认发布",
              action: () => publish.mutateAsync(),
            })
          }
        >
          <Rocket />
          发布
        </Button>
      ) : null}
      {can("workflows:publish") && data.status === "published" ? (
        <Button
          variant="destructive-outline"
          onClick={() =>
            confirm({
              title: `下线 ${name} v${version}？`,
              description: "下线后不能再用这个版本发起新运行；已有运行不受影响。版本不会被删除，但不能重新发布，只能发布新版本。",
              confirmText: "确认下线",
              danger: true,
              action: () => retire.mutateAsync(),
            })
          }
        >
          <ArchiveX />
          下线
        </Button>
      ) : null}
    </>
  );
}




const SELECT_LABEL = { first: "取第一张", gate: "交给闸门挑" };
const ON_FAIL = { fail: "整个运行失败", flag: "标记后继续", rerun_upstream: "重跑对应的上游条目" };
const ON_TIMEOUT = { wait: "一直等", approve: "自动通过", reject: "自动驳回" };

function Template({ value }) {
  if (value == null || value === "") return null;
  return (
    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-[#3a3a3a] bg-[#1b1b1c] px-2.5 py-2 font-mono text-xs leading-relaxed text-[#ccc]">
      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

function editOp(op) {
  if (op.op === "join") return `拼接${op.fade_seconds ? `，淡入淡出 ${op.fade_seconds} 秒` : ""}`;
  if (op.op === "mix") return `混音：${[op.music && `配乐 ${op.music}`, op.narration && `旁白 ${op.narration}`].filter(Boolean).join("，") || "—"}${op.duck === false ? "" : "，旁白时压低配乐"}`;
  if (op.op === "subtitle") return `字幕：${op.lines}${op.burn ? "（烧进画面）" : ""}`;
  if (op.op === "export") return `导出 ${op.format || "mp4"}${op.resolution ? ` · ${op.resolution}` : ""}${op.name ? ` · ${op.name}` : ""}`;
  return op.op;
}

/** Steps as a graph on the left and everything about the selected step on the right. */
function StepsCard({ spec, order, deps }) {
  const nodes = spec.nodes || [];
  const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
  const [picked, setPicked] = useState(null);
  const selected = picked && byId[picked] ? picked : order[0];
  const node = byId[selected] || {};
  const titleOf = (id) => byId[id]?.title || id;
  const downstream = order.filter((id) => (deps[id] || []).includes(selected));
  const chips = (ids) =>
    ids.length ? (
      <span className="flex flex-wrap gap-1">
        {ids.map((id) => (
          <button key={id} className="rounded border border-[#4e4e4e] bg-[#222] px-1.5 py-0.5 text-xs hover:border-[#0b8ce9] hover:text-white" onClick={() => setPicked(id)}>
            {titleOf(id)}
          </button>
        ))}
      </span>
    ) : (
      <span className="text-muted-foreground">无</span>
    );
  const materialize = Object.entries(node.materialize || {});
  const aliases = [...new Set([...JSON.stringify(node).matchAll(/\{\{\s*assets\.([a-z][a-z0-9_]*)/g)].map((match) => match[1]))];
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>步骤</CardTitle>
        <span className="text-[13px] text-muted-foreground">{order.length} 步 · 点一个步骤看详情</span>
      </CardHeader>
      <div className="grid border-t border-[#4e4e4e] lg:grid-cols-[300px_minmax(0,1fr)]">
        <div className="border-b border-[#4e4e4e] lg:border-r lg:border-b-0">
          <StepGraph nodes={nodes} order={order} deps={deps} selected={selected} onSelect={setPicked} />
        </div>
        {selected ? (
          <div className="min-w-0 space-y-4 p-4" data-testid="step-detail">
            <div className="flex flex-wrap items-center gap-2">
              <KindIcon kind={node.kind} className="size-5" />
              <span className="text-base font-semibold">{node.title || selected}</span>
              <Badge>{kindLabel(node.kind)}</Badge>
              <code className="text-xs text-muted-foreground">{selected}</code>
            </div>
            <KeyValues
              items={[
                ["上游", chips(deps[selected] || [])],
                ["下游", chips(downstream)],
                node.provider ? ["供应商", <code className="text-[13px]">{node.provider}</code>] : null,
                node.for_each ? ["逐条", <span>对 <code className="text-[13px]">{node.for_each}</code> 的每一项各跑一次</span>] : null,
                node.kind === "image" ? ["候选", `${node.candidates || 1} 张，${SELECT_LABEL[node.select || "first"]}`] : null,
                node.role ? ["参考用途", node.role] : null,
                node.attach_to ? ["选中的图连到", <code className="text-[13px]">{node.attach_to}</code>] : null,
                node.references?.length ? ["参考图", node.references.map((ref) => <code key={ref} className="mr-1.5 text-[13px]">{ref}</code>)] : null,
                node.template ? ["ComfyUI 模板", <code className="text-[13px]">{node.template}</code>] : null,
                node.resolution ? ["分辨率", node.resolution] : null,
                node.continuity && node.continuity !== "none" ? ["连续性", "上一镜尾帧接下一镜（镜头串行）"] : null,
                node.voice ? ["音色", <code className="text-[13px]">{node.voice}</code>] : null,
                node.duration_seconds ? ["时长", `${node.duration_seconds} 秒`] : null,
                node.rules ? ["检查", node.rules.join("、")] : null,
                node.on_fail ? ["不通过时", ON_FAIL[node.on_fail] || node.on_fail] : null,
                node.max_reruns != null ? ["最多重跑", `${node.max_reruns} 次`] : null,
                node.kind === "gate" ? ["审批", node.auto_approve ? "自动通过" : `${ROLE[node.approvers || "reviewer"] || node.approvers}审批`] : null,
                node.show ? ["审批时展示", chips(node.show)] : null,
                node.kind === "gate" ? ["驳回单条", node.allow_redo === false ? "不允许" : "允许只重跑被驳回的条目"] : null,
                node.timeout_hours ? ["超时", `${node.timeout_hours} 小时后${ON_TIMEOUT[node.on_timeout || "wait"]}`] : null,
                node.clips ? ["素材片段", <code className="text-[13px]">{node.clips}</code>] : null,
                node.repair ? ["自动修复", `最多 ${node.repair} 次`] : null,
                node.retry?.max_attempts ? ["重试", `最多 ${node.retry.max_attempts} 次${node.retry.backoff_seconds ? `，间隔 ${node.retry.backoff_seconds} 秒` : ""}`] : null,
                node.timeout_seconds ? ["超时", `${node.timeout_seconds} 秒`] : null,
                aliases.length
                  ? [
                      "用到的素材",
                      <span className="flex flex-col gap-0.5">
                        {aliases.map((alias) => (
                          <span key={alias} className="text-[13px]">
                            <code className="text-muted-foreground">assets.{alias}</code> = <code>{spec.assets?.[alias] || "未定义"}</code>
                          </span>
                        ))}
                      </span>,
                    ]
                  : null,
              ]}
            />
            {node.kind === "llm" ? (
              <div className="space-y-2">
                {node.prompt?.system ? (
                  <div>
                    <p className="mb-1 text-xs font-medium text-muted-foreground">系统提示</p>
                    <Template value={node.prompt.system} />
                  </div>
                ) : null}
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">用户提示</p>
                  <Template value={node.prompt?.user} />
                </div>
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">输出格式</p>
                  <Template value={node.output_schema} />
                </div>
                {materialize.length ? (
                  <div>
                    <p className="mb-1 text-xs font-medium text-muted-foreground">写入作品</p>
                    <ul className="space-y-1 text-[13px]">
                      {materialize.map(([field, rule]) => (
                        <li key={field}>
                          <code>{field}</code> → 每项一个「{rule.type}」
                          {rule.links?.length ? <span className="text-muted-foreground">，连到 {rule.links.map((link) => link.to).join("、")}</span> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}
            {node.kind === "video" ? (
              node.prompt && node.prompt !== "compose" ? (
                <div>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">提示词</p>
                  <Template value={node.prompt} />
                </div>
              ) : (
                <p className="text-[13px] text-muted-foreground">提示词：由镜头、风格、运镜和参考图自动组合成四段式。「预览提示词」里能看到每一镜的最终文字。</p>
              )
            ) : null}
            {["image", "music"].includes(node.kind) ? (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">提示词</p>
                <Template value={node.prompt} />
                {node.lyrics ? <Template value={node.lyrics} /> : null}
              </div>
            ) : null}
            {node.kind === "tts" ? (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">台词</p>
                <Template value={node.text || "{{item.text}}"} />
              </div>
            ) : null}
            {node.kind === "edit" ? (
              <ol className="list-inside list-decimal space-y-1 text-[13px]">
                {(node.ops || []).map((op, index) => (
                  <li key={index}>{editOp(op)}</li>
                ))}
              </ol>
            ) : null}
            <Collapsible title="这一步的原始 JSON">
              <JsonView value={node} maxHeight="20rem" />
            </Collapsible>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

const GENERATION_KINDS = ["llm", "image", "video", "tts", "music"];

/** Which provider instance every generation step uses, whether it exists, and a way to switch it. */
function ProviderBindings({ data }) {
  const { can } = useSession();
  const navigate = useNavigate();
  const client = useQueryClient();
  const { id, version } = useParams();
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get("/api/admin/providers") });
  const steps = (data.spec?.nodes || []).filter((node) => GENERATION_KINDS.includes(node.kind));
  const [picked, setPicked] = useState({});
  const items = (providers.data?.items || []).filter((item) => item.enabled);
  const choices = (kind) => {
    const names = items.filter((item) => item.kind === kind).map((item) => item.name);
    const groups = items.filter((item) => item.kind === kind && item.group_name).map((item) => item.group_name);
    return [...new Set([...groups, ...names])];
  };
  const changed = Object.entries(picked).filter(([nodeId, value]) => value && value !== steps.find((node) => node.id === nodeId)?.provider);
  const save = useMutation({
    mutationFn: () => {
      const spec = structuredClone(data.spec);
      for (const node of spec.nodes) if (picked[node.id]) node.provider = picked[node.id];
      return data.status === "draft"
        ? api.put(`/api/workflows/${id}/versions/${version}`, { spec }).then(() => ({ version: Number(version) }))
        : api.post(`/api/workflows/${id}/versions`, { spec, notes: `由 v${version} 更换供应商` });
    },
    onSuccess: (result) => {
      toast.success(data.status === "draft" ? "供应商已更新，已重新校验" : `已另存为草稿 v${result.version}`);
      setPicked({});
      client.invalidateQueries({ queryKey: ["workflow", id] });
      client.invalidateQueries({ queryKey: ["workflow-version", id] });
      if (data.status !== "draft") navigate(`/workflows/${id}/v/${result.version}`);
    },
    meta: { errorTitle: "保存失败" },
  });
  if (!steps.length) return null;
  const editable = can("workflows:draft");
  return (
    <Card>
      <CardHeader>
        <CardTitle>供应商绑定</CardTitle>
        <span className="text-[13px] text-muted-foreground">每个生成步骤用哪个供应商实例（或实例组）</span>
      </CardHeader>
      <CardContent className="space-y-2">
        {steps.map((node) => {
          const options = choices(node.kind);
          const missing = providers.data && !options.includes(node.provider);
          return (
            <div key={node.id} className="flex flex-wrap items-center gap-3 rounded-md border px-3 py-2">
              <span className="size-2 rounded-full" style={{ background: slotColor(node.kind) }} />
              <span className="min-w-28 text-[13px] font-medium">{node.title || node.id}</span>
              <Badge>{kindLabel(node.kind)}</Badge>
              <span className="flex-1" />
              {missing ? (
                <span className="flex items-center gap-1 text-xs text-[#ff9c9c]">
                  <AlertTriangle className="size-3.5" />
                  {node.provider} 不存在
                </span>
              ) : null}
              {editable ? (
                <Select
                  aria-label={`${node.title || node.id} 的供应商`}
                  className="h-8 w-56"
                  value={picked[node.id] || node.provider}
                  onChange={(event) => setPicked((current) => ({ ...current, [node.id]: event.target.value }))}
                  options={[...new Set([node.provider, ...options])].map((name) => ({
                    value: name,
                    label: options.includes(name) ? name : `${name}（未配置）`,
                  }))}
                />
              ) : (
                <code className="text-xs">{node.provider}</code>
              )}
            </div>
          );
        })}
        {providers.data && steps.some((node) => !choices(node.kind).includes(node.provider)) ? (
          <p className="text-xs text-muted-foreground">
            标红的步骤找不到供应商，运行会失败。在下拉里换成已登记的实例，或先到{" "}
            <Link className="text-primary hover:underline" to="/settings">设置 → 供应商</Link> 登记。
          </p>
        ) : null}
        {editable && changed.length ? (
          <div className="flex items-center justify-end gap-2 pt-1">
            <Button size="sm" variant="ghost" onClick={() => setPicked({})}>
              还原
            </Button>
            <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>
              {data.status === "draft" ? `保存（${changed.length} 处）` : `另存为新草稿（${changed.length} 处）`}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Overview({ data }) {
  const spec = data.spec || {};
  const order = data.graph?.order || [];
  const deps = data.graph?.deps || {};
  const validation = data.validation || { errors: [], warnings: [] };
  const inputs = Object.entries(spec.inputs?.properties || {});
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="space-y-5">
        {validation.errors?.length ? (
          <div className="rounded-lg border border-[#6a2424] bg-[#3a1717] p-3">
            <p className="mb-1 flex items-center gap-1.5 text-sm font-medium text-[#ff6e6e]">
              <XCircle className="size-4" />
              校验错误（{validation.errors.length}）
            </p>
            <ul className="list-inside list-disc space-y-0.5 text-[13px] text-[#ff9c9c]">
              {validation.errors.map((error, index) => (
                <li key={index}>{error}</li>
              ))}
            </ul>
          </div>
        ) : (
          <Notice tone="success" icon={CheckCircle2}>
            校验通过
          </Notice>
        )}
        {validation.warnings?.length ? (
          <div className="rounded-lg border border-[#6a4a18] bg-[#3a2a12] p-3">
            <p className="mb-1 flex items-center gap-1.5 text-sm font-medium text-[#ffa931]">
              <AlertTriangle className="size-4" />
              提示（{validation.warnings.length}）
            </p>
            <ul className="list-inside list-disc space-y-0.5 text-[13px] text-[#ffd18a]">
              {validation.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <StepsCard spec={spec} order={order} deps={deps} />
        <ProviderBindings data={data} />
      </div>
      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle>输入</CardTitle>
          </CardHeader>
          <CardContent>
            {inputs.length ? (
              <ul className="space-y-2 text-[13px]">
                {inputs.map(([key, prop]) => (
                  <li key={key} className="flex items-start justify-between gap-2">
                    <span>
                      {prop.title || key}
                      {(spec.inputs?.required || []).includes(key) ? <span className="text-[#ff4444]">*</span> : null}
                      <code className="ml-1.5 text-xs text-muted-foreground">{key}</code>
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {prop.format === "asset-upload" || prop.items?.format === "asset-upload"
                        ? "上传文件"
                        : prop.format === "multiline"
                          ? "长文本"
                          : prop.type === "array"
                            ? "列表"
                            : prop.type === "string"
                              ? "文本"
                              : prop.type}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-muted-foreground">没有输入</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>预算与策略</CardTitle>
          </CardHeader>
          <CardContent>
            <KeyValues
              items={[
                ["预算上限", <Money value={spec.budget?.max_yuan} digits={2} />],
                ["超预算时", spec.policy?.on_budget_exceeded === "fail" ? "直接失败" : "暂停运行"],
                ["GPU 顺序", spec.policy?.gpu_order === "round_robin" ? "多个运行轮流" : "先跑完一条"],
                ["整批屏障", spec.policy?.batch_barrier ? "开启" : "关闭"],
                spec.defaults?.resolution ? ["默认分辨率", spec.defaults.resolution] : null,
                spec.defaults?.duration ? ["默认时长", `${spec.defaults.duration} 秒`] : null,
                ["试跑样例", Object.keys(data.fixtures || {}).length ? `${Object.keys(data.fixtures).join("、")}` : "没有（预览提示词会缺少大模型输出）"],
              ]}
            />
          </CardContent>
        </Card>
        {spec.outputs ? (
          <Card>
            <CardHeader>
              <CardTitle>交付产物</CardTitle>
            </CardHeader>
            <CardContent>
              <KeyValues items={Object.entries(spec.outputs).map(([key, path]) => [key, <code className="text-xs">{path}</code>])} />
            </CardContent>
          </Card>
        ) : null}
      </div>
    </div>
  );
}

function SpecView({ spec, fixtures }) {
  const keys = Object.keys(spec || {});
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
        <Code2 className="size-4" />
        按顶层字段折叠显示；节点列表默认展开。
      </div>
      {keys.map((key) => (
        <Collapsible key={key} title={key} defaultOpen={key === "nodes"} extra={<span className="text-xs font-normal text-muted-foreground">{Array.isArray(spec[key]) ? `${spec[key].length} 项` : typeof spec[key] === "object" && spec[key] ? `${Object.keys(spec[key]).length} 个字段` : ""}</span>}>
          {key === "nodes" ? (
            <div className="space-y-1.5">
              {spec.nodes.map((node) => (
                <Collapsible key={node.id} title={`${node.id} · ${kindLabel(node.kind)}${node.title ? ` · ${node.title}` : ""}`}>
                  <JsonView value={node} />
                </Collapsible>
              ))}
            </div>
          ) : (
            <JsonView value={spec[key]} />
          )}
        </Collapsible>
      ))}
      {fixtures && Object.keys(fixtures).length ? (
        <Collapsible title="试跑样例（fixtures）">
          <JsonView value={fixtures} />
        </Collapsible>
      ) : null}
    </div>
  );
}

function DiffView({ id, version, versions, previous }) {
  const [base, setBase] = useState(previous || "");
  const diff = useQuery({
    queryKey: ["workflow-diff", id, base, version],
    queryFn: () => api.get(`/api/workflows/${id}/diff?base=${base}&head=${version}`),
    enabled: Boolean(base),
  });
  const others = versions.filter((item) => item.version !== version);
  if (!others.length) return <EmptyState icon={GitCompare} title="这是第一个版本" description="之后提交的新版本会在这里显示与上一版的差异。" />;
  const lines = (diff.data?.diff || "").split("\n");
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-[13px]">
        <span className="text-muted-foreground">对比</span>
        <Select className="w-32" value={base} onChange={(event) => setBase(Number(event.target.value))} options={others.map((item) => ({ value: item.version, label: `v${item.version}` }))} />
        <span className="text-muted-foreground">→ v{version}</span>
      </div>
      {!diff.data && diff.isLoading ? (
        <SkeletonRows rows={4} />
      ) : diff.isError ? (
        <ErrorState error={diff.error} retry={diff.refetch} />
      ) : !diff.data?.diff ? (
        <Notice tone="info">两个版本的规格完全相同。</Notice>
      ) : (
        <Card className="overflow-auto">
          <pre className="min-w-max p-0 text-xs leading-5">
            {lines.map((line, index) => (
              <div
                key={index}
                className={cn(
                  "px-3",
                  line.startsWith("+") && !line.startsWith("+++") && "diff-add",
                  line.startsWith("-") && !line.startsWith("---") && "diff-del",
                  line.startsWith("@@") && "diff-hunk",
                  (line.startsWith("+++") || line.startsWith("---")) && "font-semibold text-muted-foreground",
                )}
              >
                {line || " "}
              </div>
            ))}
          </pre>
        </Card>
      )}
    </div>
  );
}

function CompileForm({ id, version, data, canRun }) {
  const { workspaceId } = useSession();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const schema = data.spec?.inputs || { type: "object" };
  const [mode, setMode] = useState("form");
  const [values, setValues] = useState(() => initialValues(schema));
  const [raw, setRaw] = useState("{}");
  const [errors, setErrors] = useState({});
  const [rawError, setRawError] = useState("");
  const hasFixtures = Object.keys(data.fixtures || {}).length > 0;
  const hasLlm = (data.spec?.nodes || []).some((node) => node.kind === "llm");

  const inputs = useMemo(() => {
    if (mode === "json") {
      try {
        return JSON.parse(raw || "{}");
      } catch {
        return null;
      }
    }
    return toInputs(schema, values);
  }, [mode, raw, values, schema]);

  const compile = useMutation({
    mutationFn: (payload) => api.post(`/api/workflows/${id}/versions/${version}/dry-run`, { inputs: payload, level: "compile" }),
    meta: { inline: true },
  });
  const llmRun = useMutation({
    mutationFn: (payload) => api.post(`/api/workflows/${id}/versions/${version}/dry-run`, { inputs: payload, level: "llm" }),
    onSuccess: (result) => {
      toast.success("大模型试跑已排队", "跳转到运行页查看进度");
      navigate(`/runs/${result.run_id}`);
    },
  });

  const check = () => {
    if (mode === "json") {
      if (inputs === null) {
        setRawError("JSON 格式不对");
        return false;
      }
      setRawError("");
      return true;
    }
    const found = validate(schema, values);
    setErrors(found);
    return !Object.keys(found).length;
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[400px_minmax(0,1fr)]">
      <Card className="h-fit">
        <CardHeader>
          <div>
            <CardTitle>试跑输入</CardTitle>
            <p className="text-[13px] text-muted-foreground">预览提示词不调用任何供应商，不花钱：用试跑样例代替大模型输出，算出每一条最终提示词和花费估算。</p>
          </div>
          <div className="inline-flex rounded-md border bg-card p-0.5 text-xs">
            {[
              ["form", "表单"],
              ["json", "JSON"],
            ].map(([value, label]) => (
              <button
                key={value}
                className={cn("h-6 rounded px-2 text-muted-foreground", mode === value && "bg-accent font-medium text-accent-foreground")}
                onClick={() => {
                  if (value === "json") setRaw(JSON.stringify(toInputs(schema, values), null, 2));
                  setMode(value);
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {hasLlm && !hasFixtures ? (
            <Notice tone="warn" icon={AlertTriangle}>
              这个版本没有试跑样例（fixtures），预览提示词拿不到大模型步骤的输出。
            </Notice>
          ) : null}
          {mode === "form" ? (
            <SchemaForm schema={schema} values={values} onChange={setValues} errors={errors} workspaceId={workspaceId} idPrefix="dry" />
          ) : (
            <div className="space-y-1.5">
              <Textarea className="font-mono text-xs" rows={12} value={raw} onChange={(event) => setRaw(event.target.value)} aria-invalid={Boolean(rawError) || undefined} />
              {rawError ? <p className="text-xs text-[#ff4444]">{rawError}</p> : null}
            </div>
          )}
          {compile.isError ? <InlineError>{compile.error.message}</InlineError> : null}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => check() && compile.mutate(inputs)} loading={compile.isPending}>
              <FlaskConical />
              预览提示词
            </Button>
            {hasLlm && canRun ? (
              <Button
                variant="outline"
                onClick={() =>
                  check() &&
                  confirm({
                    title: "发起大模型试跑？",
                    description: "会真实调用大模型，编译出全部视频提示词。不生成图片和视频。",
                    spends: "只花大模型的钱",
                    confirmText: "发起试跑",
                    action: () => llmRun.mutateAsync(inputs),
                  })
                }
              >
                大模型试跑
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>
      <div>
        {compile.data ? (
          <Card>
            <CardHeader>
              <CardTitle>编译结果</CardTitle>
            </CardHeader>
            <CardContent>
              <CompileResult result={compile.data} budget={data.spec?.budget?.max_yuan} />
            </CardContent>
          </Card>
        ) : (
          <EmptyState icon={FlaskConical} title="还没有试跑结果" description="填好左侧输入后点「预览提示词」，这里会列出每一条最终提示词和逐项花费估算。" />
        )}
      </div>
    </div>
  );
}
