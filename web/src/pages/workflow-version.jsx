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
import { StepGraph } from "@/components/step-graph";
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
      {detail.isLoading ? (
        <SkeletonRows rows={6} />
      ) : (
        <Tabs value={tab} onValueChange={(value) => setParams(value === "overview" ? {} : { tab: value }, { replace: true })}>
          <TabsList>
            <TabsTrigger value="overview">概览与步骤</TabsTrigger>
            <TabsTrigger value="spec">规格 JSON</TabsTrigger>
            <TabsTrigger value="diff">与上一版的差异</TabsTrigger>
            <TabsTrigger value="compile">编译试跑</TabsTrigger>
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

function nodeSummary(node) {
  const parts = [];
  if (node.provider) parts.push(`供应商 ${node.provider}`);
  if (node.for_each) parts.push(`逐条：${node.for_each}`);
  if (node.candidates) parts.push(`${node.candidates} 张候选`);
  if (node.select === "gate") parts.push("由闸门挑选");
  if (node.approvers) parts.push(`审批：${ROLE[node.approvers] || node.approvers}`);
  if (node.auto_approve) parts.push("自动通过");
  if (node.show) parts.push(`展示 ${node.show.join("、")}`);
  if (node.rules) parts.push(`检查 ${node.rules.join("、")}`);
  if (node.continuity && node.continuity !== "none") parts.push(`连续性 ${node.continuity}`);
  if (node.repair) parts.push(`修复 ${node.repair} 次`);
  if (node.retry?.max_attempts) parts.push(`最多尝试 ${node.retry.max_attempts} 次`);
  return parts;
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
  const nodes = Object.fromEntries((spec.nodes || []).map((node) => [node.id, node]));
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
        <ProviderBindings data={data} />
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle>步骤图</CardTitle>
            <span className="tnum text-[13px] text-muted-foreground">{order.length} 步</span>
          </CardHeader>
          <StepGraph
            nodes={spec.nodes || []}
            order={order}
            deps={deps}
            summaries={Object.fromEntries(order.map((nodeId) => [nodeId, nodeSummary(nodes[nodeId] || {}).join(" · ")]))}
          />
          <ol className="relative border-t border-[#4e4e4e]">
            {order.map((nodeId, index) => {
              const node = nodes[nodeId] || {};
              const summary = nodeSummary(node);
              const color = slotColor(node.kind);
              return (
                <li key={nodeId} className="relative flex gap-3 px-4 py-3">
                  <div className="flex flex-col items-center">
                    <span className="tnum flex size-6 items-center justify-center rounded-full border text-xs font-semibold" style={{ borderColor: color, color }}>{index + 1}</span>
                    {index < order.length - 1 ? <span className="mt-1 w-px flex-1 bg-border" /> : null}
                  </div>
                  <div className="min-w-0 flex-1 pb-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="size-2 rounded-full" style={{ background: color }} />
                      <span className="text-sm font-medium">{node.title || nodeId}</span>
                      <Badge>{kindLabel(node.kind)}</Badge>
                      <code className="text-xs text-muted-foreground">{nodeId}</code>
                    </div>
                    {deps[nodeId]?.length ? <p className="mt-0.5 text-xs text-muted-foreground">依赖：{deps[nodeId].join("、")}</p> : <p className="mt-0.5 text-xs text-muted-foreground">起点</p>}
                    {summary.length ? <p className="mt-0.5 text-[13px] text-[#ccc]">{summary.join(" · ")}</p> : null}
                    {typeof node.prompt === "string" && node.prompt !== "compose" ? (
                      <p className="mt-1 line-clamp-2 rounded bg-[#222] px-2 py-1 font-mono text-xs text-muted-foreground">{node.prompt}</p>
                    ) : node.prompt === "compose" ? (
                      <p className="mt-1 text-xs text-muted-foreground">提示词：由本体组合四段式提示词</p>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </Card>
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
                ["试跑样例", Object.keys(data.fixtures || {}).length ? `${Object.keys(data.fixtures).join("、")}` : "没有（编译试跑会缺少大模型输出）"],
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
      {diff.isLoading ? (
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
            <p className="text-[13px] text-muted-foreground">编译试跑不调用任何供应商，不花钱。</p>
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
              这个版本没有试跑样例（fixtures），编译试跑拿不到大模型步骤的输出。
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
              编译试跑
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
          <EmptyState icon={FlaskConical} title="还没有试跑结果" description="填好左侧输入后点「编译试跑」，这里会列出每一条最终提示词和逐项花费估算。" />
        )}
      </div>
    </div>
  );
}
