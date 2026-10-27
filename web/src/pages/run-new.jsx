import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Copy, Layers, Play, Plus, Trash2, Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Switch } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { EmptyState, ErrorState, InlineError, KeyValues, Money, Notice, PageHeader, SkeletonRows, useConfirm, useDocumentTitle } from "@/components/common";
import { EstimateTable } from "@/components/compile-result";
import { SchemaForm, initialValues, toInputs, validate } from "@/components/schema-form";
import { api, qs } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

export default function RunNewPage() {
  const { workspaceId, can } = useSession();
  const [params, setParams] = useSearchParams();
  const workflowId = params.get("workflow") || "";
  useDocumentTitle("发起运行");
  const workflows = useQuery({
    queryKey: ["workflows", workspaceId],
    queryFn: () => api.get(`/api/workflows${qs({ workspace_id: workspaceId })}`),
    enabled: Boolean(workspaceId),
  });
  const published = (workflows.data?.items || []).filter((item) => item.published_version);
  const selected = published.find((item) => item.id === workflowId);

  useEffect(() => {
    if (!workflowId && published.length === 1) setParams({ workflow: published[0].id }, { replace: true });
  }, [workflowId, published, setParams]);

  if (!can("runs:create")) {
    return (
      <div>
        <PageHeader title="发起运行" back={{ to: "/runs", label: "运行" }} />
        <ErrorState error={{ status: 403, message: "你的角色不能发起运行" }} />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="发起运行" back={{ to: "/runs", label: "运行" }} description="只能提交九步漫剧工作流，并带上剧本。不能新开一条灵感出片运行。" />
      {!workflows.data && (workflows.isLoading || workflows.isPending) ? (
        <SkeletonRows rows={3} />
      ) : workflows.isError ? (
        <ErrorState error={workflows.error} retry={workflows.refetch} />
      ) : !published.length ? (
        <EmptyState icon={Workflow} title="还没有已发布的工作流" description="工作流要由审计员审核发布后才能用来发起运行。" action={<Button asChild size="sm" variant="outline"><Link to="/workflows">查看工作流</Link></Button>} />
      ) : (
        <div className="space-y-5">
          <Card>
            <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <Field label="工作流" htmlFor="workflow" className="sm:w-80">
                <Select
                  id="workflow"
                  value={workflowId}
                  onChange={(event) => setParams(event.target.value ? { workflow: event.target.value } : {}, { replace: true })}
                  placeholder="选择工作流"
                  options={published.map((item) => ({ value: item.id, label: `${item.name}（v${item.published_version}）` }))}
                />
              </Field>
              {selected?.description ? <p className="flex-1 text-[13px] text-muted-foreground sm:pb-2">{selected.description}</p> : null}
            </CardContent>
          </Card>
          {selected ? <RunForm key={selected.id} workflow={selected} /> : <EmptyState compact icon={Workflow} title="先选择一个工作流" description="表单会按工作流声明的输入自动生成。" />}
        </div>
      )}
    </div>
  );
}

function RunForm({ workflow }) {
  const { workspaceId } = useSession();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const version = workflow.published_version;
  const detail = useQuery({
    queryKey: ["workflow-version", workflow.id, String(version)],
    queryFn: () => api.get(`/api/workflows/${workflow.id}/versions/${version}`),
  });
  const schema = detail.data?.spec?.inputs || { type: "object" };
  const budget = detail.data?.spec?.budget?.max_yuan;
  const hasFixtures = Object.keys(detail.data?.fixtures || {}).length > 0;
  const gates = (detail.data?.spec?.nodes || []).filter((node) => node.kind === "gate" && !node.auto_approve);

  const [batch, setBatch] = useState(false);
  const [rows, setRows] = useState(null);
  const [errors, setErrors] = useState([]);
  const [priority, setPriority] = useState("0");
  const [autoGates, setAutoGates] = useState(false);
  const [estimate, setEstimate] = useState(null);

  useEffect(() => {
    if (detail.data && rows === null) setRows([initialValues(schema)]);
  }, [detail.data, rows, schema]);

  const estimateRows = async (list) => {
    const results = [];
    for (const values of list) {
      results.push(await api.post(`/api/workflows/${workflow.id}/versions/${version}/dry-run`, { inputs: toInputs(schema, values), level: "compile" }));
    }
    return results;
  };

  const estimateMutation = useMutation({
    mutationFn: () => estimateRows(batch ? rows : rows.slice(0, 1)),
    onSuccess: (results) => setEstimate(results),
    meta: { errorTitle: "估算失败" },
  });

  const submit = useMutation({
    mutationFn: () => {
      const inputs = (batch ? rows : rows.slice(0, 1)).map((values) => toInputs(schema, values));
      const common = { workflow_id: workflow.id, version, priority: Number(priority), auto_gates: autoGates };
      return batch && inputs.length > 1 ? api.post("/api/batches", { ...common, inputs }) : api.post("/api/runs", { ...common, inputs: inputs[0] });
    },
    onSuccess: (result) => {
      if (result.batch_id) {
        toast.success(`已发起 ${result.runs.length} 个运行`, "可以在运行列表里查看进度");
        navigate(`/runs?workflow=${workflow.id}`);
      } else {
        toast.success("运行已发起", "正在排队执行");
        navigate(`/runs/${result.id}`);
      }
    },
  });

  if ((!detail.data && detail.isLoading) || rows === null) return <SkeletonRows rows={4} />;
  if (detail.isError) return <ErrorState error={detail.error} retry={detail.refetch} />;

  const active = batch ? rows : rows.slice(0, 1);
  const check = () => {
    const found = active.map((values) => validate(schema, values));
    setErrors(found);
    const bad = found.findIndex((item) => Object.keys(item).length);
    if (bad >= 0) {
      toast.error("请先把表单填完整", batch ? `第 ${bad + 1} 组有问题` : undefined);
      return false;
    }
    return true;
  };

  const start = async () => {
    if (!check()) return;
    let results = estimate && estimate.length === active.length ? estimate : null;
    if (hasFixtures && !results) {
      try {
        results = await estimateMutation.mutateAsync();
      } catch {
        return;
      }
    }
    const total = results ? results.reduce((sum, item) => sum + (item.estimate_yuan || 0), 0) : null;
    confirm({
      title: active.length > 1 ? `发起 ${active.length} 个运行？` : "发起运行？",
      description: `${workflow.name} v${version}${gates.length && !autoGates ? `。运行会在「${gates.map((gate) => gate.title || gate.id).join("、")}」停下等人审批` : ""}`,
      spends: total !== null ? `估算约 ¥${total.toFixed(2)}` : `无法预先估算，单个运行预算上限 ¥${budget ?? "—"}`,
      body: results ? (
        <div className="space-y-2">
          <KeyValues
            items={[
              ["估算合计", <Money value={total} digits={2} className="font-semibold" />],
              ["单个预算上限", <Money value={budget} digits={2} />],
            ]}
          />
          {results.length === 1 ? <EstimateTable breakdown={results[0].breakdown} /> : null}
          {results.some((item) => item.problems?.length) ? <InlineError>编译发现问题：{results.flatMap((item) => item.problems).join("；")}</InlineError> : null}
        </div>
      ) : null,
      confirmText: active.length > 1 ? `发起 ${active.length} 个运行` : "确认发起",
      action: () => submit.mutateAsync(),
    });
  };

  const setRow = (index, values) => {
    setRows((current) => current.map((row, i) => (i === index ? values : row)));
    setEstimate(null);
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div className="inline-flex rounded-md border bg-card p-0.5">
            {[
              [false, "单个运行"],
              [true, "批量"],
            ].map(([value, label]) => (
              <button
                key={label}
                className={cn("h-7 rounded px-3 text-[13px] text-muted-foreground", batch === value && "bg-accent font-medium text-accent-foreground")}
                onClick={() => {
                  setBatch(value);
                  setEstimate(null);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {batch ? <span className="tnum text-[13px] text-muted-foreground">{rows.length} 组输入</span> : null}
        </div>
        {active.map((values, index) => (
          <Card key={index}>
            {batch ? (
              <CardHeader className="py-2.5">
                <CardTitle className="text-sm">第 {index + 1} 组</CardTitle>
                <div className="flex gap-1">
                  <Button size="xs" variant="ghost" onClick={() => setRows((current) => [...current.slice(0, index + 1), { ...values }, ...current.slice(index + 1)])}>
                    <Copy />
                    复制
                  </Button>
                  {rows.length > 1 ? (
                    <Button size="xs" variant="ghost" className="text-[#ff9c9c]" onClick={() => setRows((current) => current.filter((_, i) => i !== index))}>
                      <Trash2 />
                      删除
                    </Button>
                  ) : null}
                </div>
              </CardHeader>
            ) : null}
            <CardContent>
              <SchemaForm schema={schema} values={values} onChange={(next) => setRow(index, next)} errors={errors[index] || {}} workspaceId={workspaceId} idPrefix={`row${index}`} />
            </CardContent>
          </Card>
        ))}
        {batch ? (
          <Button variant="outline" className="w-full border-dashed" onClick={() => setRows((current) => [...current, initialValues(schema)])} disabled={rows.length >= 200}>
            <Plus />
            添加一组输入
          </Button>
        ) : null}
      </div>
      <div className="space-y-4 xl:sticky xl:top-20 xl:self-start">
        <Card>
          <CardHeader>
            <CardTitle>花费与选项</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <KeyValues
              items={[
                ["版本", `v${version}`],
                ["单个预算上限", <Money value={budget} digits={2} />],
                ["审批闸门", gates.length ? gates.map((gate) => gate.title || gate.id).join("、") : "无，全程自动"],
              ]}
            />
            {hasFixtures ? (
              <div className="rounded-md border bg-[#222] p-3">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] text-muted-foreground">编译估算{batch && active.length > 1 ? `（${active.length} 组合计）` : ""}</span>
                  <Button size="xs" variant="outline" onClick={() => check() && estimateMutation.mutate()} loading={estimateMutation.isPending}>
                    估算
                  </Button>
                </div>
                <p className="tnum mt-1 text-xl font-semibold">
                  {estimate ? <Money value={estimate.reduce((sum, item) => sum + (item.estimate_yuan || 0), 0)} digits={2} /> : <span className="text-muted-foreground">—</span>}
                </p>
                {estimate ? <p className="text-xs text-muted-foreground">基于试跑样例，实际以运行时为准</p> : <p className="text-xs text-muted-foreground">填好表单后点「估算」，不花钱</p>}
              </div>
            ) : (
              <Notice tone="info" icon={AlertTriangle}>
                这个工作流没有试跑样例，无法预先估算花费；运行超出预算上限时会自动{detail.data?.spec?.policy?.on_budget_exceeded === "fail" ? "失败" : "暂停"}。
              </Notice>
            )}
            <Field label="优先级" htmlFor="priority">
              <Select
                id="priority"
                value={priority}
                onChange={(event) => setPriority(event.target.value)}
                options={[
                  { value: "0", label: "普通" },
                  { value: "10", label: "加急（+10）" },
                  { value: "-10", label: "不急（-10）" },
                ]}
              />
            </Field>
            {gates.length ? (
              <label className="flex items-start justify-between gap-3">
                <span>
                  <span className="block text-[13px] font-medium">闸门自动通过</span>
                  <span className="block text-xs text-muted-foreground">不停下来等人审，直接生成视频</span>
                </span>
                <Switch checked={autoGates} onCheckedChange={setAutoGates} />
              </label>
            ) : null}
            <Button className="w-full" size="lg" onClick={start} loading={submit.isPending || estimateMutation.isPending}>
              {batch && active.length > 1 ? <Layers /> : <Play />}
              {batch && active.length > 1 ? `发起 ${active.length} 个运行` : "发起运行"}
            </Button>
            <p className="text-center text-xs text-muted-foreground">提交前会再次确认花费</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
