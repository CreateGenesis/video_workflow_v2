import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, KeyRound, List, MoreHorizontal, Pencil, Plus, Server, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select, Textarea } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Switch,
  TBody,
  THead,
  Table,
  Tooltip,
} from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { EmptyState, InlineError, JsonView, Notice, QueryView, SkeletonRows, Time, useConfirm } from "@/components/common";
import { api } from "@/lib/api";
import { PRICING_UNIT, PROTOCOLS, PROVIDER_KINDS, kindLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";

function healthBadge(health) {
  if (!health || !Object.keys(health).length) return <Badge>未探测</Badge>;
  return (
    <Tooltip content={`${health.message || health.error || ""}${health.checked_at ? ` · ${new Date(health.checked_at).toLocaleString("zh-CN")}` : ""}`}>
      <span>{health.reachable ? <Badge tone="green" dot>正常</Badge> : <Badge tone="red" dot>异常</Badge>}</span>
    </Tooltip>
  );
}

export default function ProvidersTab() {
  const client = useQueryClient();
  const confirm = useConfirm();
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get("/api/admin/providers") });
  const [editing, setEditing] = useState(null);
  const [probe, setProbe] = useState(null);
  const [models, setModels] = useState(null);

  const runProbe = useMutation({
    mutationFn: (name) => api.post(`/api/admin/providers/${encodeURIComponent(name)}/probe`),
    onSuccess: (result, name) => {
      setProbe({ name, result });
      client.invalidateQueries({ queryKey: ["providers"] });
    },
    meta: { errorTitle: "探测失败" },
  });
  const listModels = useMutation({
    mutationFn: (name) => api.get(`/api/admin/providers/${encodeURIComponent(name)}/models`),
    onSuccess: (result, name) => setModels({ name, items: result.items }),
    meta: { errorTitle: "获取模型列表失败" },
  });
  const remove = useMutation({
    mutationFn: (name) => api.del(`/api/admin/providers/${encodeURIComponent(name)}`),
    onSuccess: (_d, name) => {
      toast.success(`已删除 ${name}`);
      client.invalidateQueries({ queryKey: ["providers"] });
    },
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">每个供应商实例对应一个接口地址和密钥。工作流按实例名或实例组引用。密钥加密保存，只显示后四位。</p>
        <Button size="sm" onClick={() => setEditing({})}>
          <Plus />
          新增供应商
        </Button>
      </div>
      <QueryView query={providers} skeleton={<SkeletonRows rows={5} />}>
        {(data) =>
          data.items.length ? (
            <Card className="overflow-hidden">
              <Table>
                <THead>
                  <tr>
                    <th>实例</th>
                    <th>类型 / 协议</th>
                    <th className="hidden lg:table-cell">资源池</th>
                    <th className="hidden md:table-cell">模型</th>
                    <th>密钥</th>
                    <th>健康</th>
                    <th />
                  </tr>
                </THead>
                <TBody>
                  {data.items.map((item) => (
                    <tr key={item.name} className={cn(!item.enabled && "opacity-60")}>
                      <td>
                        <div className="flex items-center gap-1.5 font-medium">
                          <Server className="size-3.5 text-muted-foreground" />
                          {item.name}
                          {!item.enabled ? <Badge>已停用</Badge> : null}
                        </div>
                        {item.group_name ? <div className="text-xs text-muted-foreground">组 {item.group_name}</div> : null}
                        {item.base_url ? <div className="max-w-56 truncate text-xs text-muted-foreground">{item.base_url}</div> : null}
                      </td>
                      <td className="whitespace-nowrap text-[13px]">
                        {kindLabel(item.kind)}
                        <span className="text-muted-foreground"> · {PROTOCOLS.find((p) => p.value === item.protocol)?.label || item.protocol}</span>
                      </td>
                      <td className="hidden text-[13px] lg:table-cell">{item.pool}</td>
                      <td className="hidden max-w-40 truncate text-[13px] md:table-cell">{item.model || <span className="text-muted-foreground">—</span>}</td>
                      <td className="whitespace-nowrap text-[13px]">
                        {item.secret ? <code className="text-xs">{item.secret}</code> : item.configured ? <span className="text-muted-foreground">无需密钥</span> : <span className="text-[#ffa931]">未配置</span>}
                      </td>
                      <td>{healthBadge(item.health)}</td>
                      <td className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button size="xs" variant="outline" onClick={() => runProbe.mutate(item.name)} loading={runProbe.isPending && runProbe.variables === item.name}>
                            <Activity />
                            探测
                          </Button>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button size="icon-sm" variant="ghost" className="size-7" aria-label="更多操作">
                                <MoreHorizontal />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent>
                              <DropdownMenuItem onSelect={() => setEditing(item)}>
                                <Pencil />
                                编辑
                              </DropdownMenuItem>
                              <DropdownMenuItem onSelect={() => listModels.mutate(item.name)}>
                                <List />
                                模型列表
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                danger
                                onSelect={() =>
                                  confirm({
                                    title: `删除供应商 ${item.name}？`,
                                    description: "引用它的工作流会校验失败，正在排队的任务找不到供应商。这个操作不能撤销。",
                                    confirmText: "删除",
                                    danger: true,
                                    action: () => remove.mutateAsync(item.name),
                                  })
                                }
                              >
                                <Trash2 />
                                删除
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </td>
                    </tr>
                  ))}
                </TBody>
              </Table>
            </Card>
          ) : (
            <EmptyState icon={Server} title="还没有供应商实例" description="先登记大模型、生图、视频等供应商，工作流才能执行。" />
          )
        }
      </QueryView>
      {editing ? <ProviderDialog initial={editing} onClose={() => setEditing(null)} /> : null}
      <Dialog open={Boolean(probe)} onOpenChange={(open) => (!open ? setProbe(null) : null)}>
        {probe ? (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>探测结果 · {probe.name}</DialogTitle>
            </DialogHeader>
            <DialogBody className="space-y-2">
              {probe.result.reachable ? <Notice tone="success">{probe.result.message || "连接正常"}</Notice> : <InlineError>{probe.result.message || probe.result.error || "探测失败"}</InlineError>}
              <JsonView value={probe.result} maxHeight="20rem" />
            </DialogBody>
          </DialogContent>
        ) : null}
      </Dialog>
      <Dialog open={Boolean(models)} onOpenChange={(open) => (!open ? setModels(null) : null)}>
        {models ? (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>可用模型 · {models.name}</DialogTitle>
              <DialogDescription>共 {models.items.length} 个</DialogDescription>
            </DialogHeader>
            <DialogBody>
              {models.items.length ? (
                <ul className="divide-y rounded-md border text-[13px]">
                  {models.items.map((model, index) => (
                    <li key={index} className="px-3 py-1.5 font-mono text-xs">
                      {typeof model === "string" ? model : model.id || JSON.stringify(model)}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-muted-foreground">供应商没有返回模型列表。</p>
              )}
            </DialogBody>
          </DialogContent>
        ) : null}
      </Dialog>
    </div>
  );
}

function jsonText(value) {
  return value && Object.keys(value).length ? JSON.stringify(value, null, 2) : "{}";
}

function parseJson(text) {
  try {
    const value = JSON.parse(text || "{}");
    if (typeof value !== "object" || Array.isArray(value) || value === null) return [null, "需要一个 JSON 对象"];
    return [value, ""];
  } catch (error) {
    return [null, `JSON 格式不对：${error.message}`];
  }
}

function ProviderDialog({ initial, onClose }) {
  const client = useQueryClient();
  const creating = !initial.name;
  const [form, setForm] = useState({
    name: initial.name || "",
    kind: initial.kind || "llm",
    protocol: initial.protocol || "openai-chat",
    group_name: initial.group_name || "",
    base_url: initial.base_url || "",
    model: initial.model || "",
    pool: initial.pool || "",
    retry_safe: initial.retry_safe ?? true,
    max_attempts: String(initial.max_attempts ?? 3),
    timeout_seconds: String(initial.timeout_seconds ?? 1800),
    enabled: initial.enabled ?? true,
    secret: "",
    clear_secret: false,
    pricing: jsonText(initial.pricing),
    options: jsonText(initial.options),
    capabilities: jsonText(initial.capabilities),
  });
  const [touched, setTouched] = useState(false);
  const set = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));
  const protocols = PROTOCOLS.filter((item) => item.kinds.includes(form.kind));
  const parsed = useMemo(
    () => ({ pricing: parseJson(form.pricing), options: parseJson(form.options), capabilities: parseJson(form.capabilities) }),
    [form.pricing, form.options, form.capabilities],
  );
  const problems = {
    name: !form.name.trim() ? "请填写实例名" : !/^[\w.\-]+$/.test(form.name.trim()) ? "只能用字母、数字、点、横线和下划线" : "",
    protocol: !protocols.some((item) => item.value === form.protocol) ? "这个协议不能用于该类型" : "",
    pricing: parsed.pricing[1],
    options: parsed.options[1],
    capabilities: parsed.capabilities[1],
    max_attempts: !/^\d+$/.test(form.max_attempts) || Number(form.max_attempts) < 1 ? "至少 1 次" : "",
    timeout_seconds: !/^\d+$/.test(form.timeout_seconds) ? "请输入秒数" : "",
  };
  const valid = Object.values(problems).every((value) => !value);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        kind: form.kind,
        protocol: form.protocol,
        group_name: form.group_name.trim() || null,
        base_url: form.base_url.trim(),
        model: form.model.trim(),
        retry_safe: form.retry_safe,
        max_attempts: Number(form.max_attempts),
        timeout_seconds: Number(form.timeout_seconds),
        enabled: form.enabled,
        pricing: parsed.pricing[0],
        options: parsed.options[0],
        capabilities: parsed.capabilities[0],
      };
      if (form.pool.trim()) body.pool = form.pool.trim();
      if (form.secret) body.secret = form.secret;
      if (form.clear_secret) body.clear_secret = true;
      return api.post("/api/admin/providers", body);
    },
    onSuccess: () => {
      toast.success(creating ? `已新增 ${form.name}` : `已保存 ${form.name}`);
      client.invalidateQueries();
      onClose();
    },
    meta: { inline: true },
  });
  const show = (key) => touched && problems[key];
  const units = Object.keys(PRICING_UNIT).join("、");
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle>{creating ? "新增供应商实例" : `编辑 ${initial.name}`}</DialogTitle>
          <DialogDescription>改动立即生效，新任务会用新配置。</DialogDescription>
        </DialogHeader>
        <DialogBody>
          <form
            id="provider-form"
            className="grid gap-4 sm:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              setTouched(true);
              if (valid) save.mutate();
            }}
          >
            <Field label="实例名" htmlFor="p-name" required error={show("name")} hint={creating ? "例如 llm.deepseek、video.comfy-gpu2" : "实例名不能修改"}>
              <Input id="p-name" value={form.name} onChange={(event) => set("name")(event.target.value)} disabled={!creating} aria-invalid={Boolean(show("name")) || undefined} />
            </Field>
            <Field label="类型" htmlFor="p-kind" required>
              <Select
                id="p-kind"
                value={form.kind}
                onChange={(event) => {
                  const kind = event.target.value;
                  const allowed = PROTOCOLS.filter((item) => item.kinds.includes(kind));
                  setForm((current) => ({ ...current, kind, protocol: allowed.some((item) => item.value === current.protocol) ? current.protocol : allowed[0].value }));
                }}
                options={PROVIDER_KINDS.map((kind) => ({ value: kind, label: kindLabel(kind) }))}
              />
            </Field>
            <Field label="协议" htmlFor="p-protocol" required error={show("protocol")}>
              <Select id="p-protocol" value={form.protocol} onChange={(event) => set("protocol")(event.target.value)} options={protocols} />
            </Field>
            <Field label="实例组" htmlFor="p-group" hint="同组实例可互相替代，例如 video.comfy">
              <Input id="p-group" value={form.group_name} onChange={(event) => set("group_name")(event.target.value)} />
            </Field>
            <Field label="接口地址" htmlFor="p-base" className="sm:col-span-2" hint="官方接口、兼容网关或自部署服务的 base URL">
              <Input id="p-base" value={form.base_url} onChange={(event) => set("base_url")(event.target.value)} placeholder="https://" />
            </Field>
            <Field label="模型" htmlFor="p-model">
              <Input id="p-model" value={form.model} onChange={(event) => set("model")(event.target.value)} />
            </Field>
            <Field label="资源池" htmlFor="p-pool" hint="留空按类型使用默认池">
              <Input id="p-pool" value={form.pool} onChange={(event) => set("pool")(event.target.value)} />
            </Field>
            <Field
              label="密钥"
              htmlFor="p-secret"
              className="sm:col-span-2"
              hint={initial.secret ? `已配置（${initial.secret}）。留空表示不修改。` : "加密保存，任何接口都不会返回明文。"}
            >
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <div className="relative flex-1">
                  <KeyRound className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="p-secret"
                    type="password"
                    autoComplete="new-password"
                    className="pl-8"
                    value={form.secret}
                    disabled={form.clear_secret}
                    placeholder={initial.secret ? "••••••••（不修改）" : "粘贴密钥"}
                    onChange={(event) => set("secret")(event.target.value)}
                  />
                </div>
                {initial.secret ? (
                  <label className="flex items-center gap-1.5 text-[13px] text-[#ff9c9c]">
                    <input type="checkbox" className="accent-red-600" checked={form.clear_secret} onChange={(event) => set("clear_secret")(event.target.checked)} />
                    清除已保存的密钥
                  </label>
                ) : null}
              </div>
            </Field>
            <Field label="最多尝试次数" htmlFor="p-attempts" error={show("max_attempts")} hint={!form.retry_safe ? "不可安全重试的供应商只会执行 1 次" : undefined}>
              <Input id="p-attempts" type="number" min={1} className="tnum" value={form.max_attempts} onChange={(event) => set("max_attempts")(event.target.value)} />
            </Field>
            <Field label="超时（秒）" htmlFor="p-timeout" error={show("timeout_seconds")}>
              <Input id="p-timeout" type="number" min={1} className="tnum" value={form.timeout_seconds} onChange={(event) => set("timeout_seconds")(event.target.value)} />
            </Field>
            <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
              <span>
                <span className="block text-[13px] font-medium">可安全重试</span>
                <span className="block text-xs text-muted-foreground">按次计费的供应商要关掉，避免重复扣费</span>
              </span>
              <Switch checked={form.retry_safe} onCheckedChange={set("retry_safe")} />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
              <span>
                <span className="block text-[13px] font-medium">启用</span>
                <span className="block text-xs text-muted-foreground">停用后不再领取新任务</span>
              </span>
              <Switch checked={form.enabled} onCheckedChange={set("enabled")} />
            </label>
            <Field label="单价（JSON）" htmlFor="p-pricing" className="sm:col-span-2" error={show("pricing")} hint={`单位 → 每单位元。常用单位：${units}`}>
              <Textarea id="p-pricing" className="font-mono text-xs" rows={4} value={form.pricing} onChange={(event) => set("pricing")(event.target.value)} aria-invalid={Boolean(problems.pricing) || undefined} />
            </Field>
            <Field label="选项（JSON）" htmlFor="p-options" error={problems.options} hint="协议相关的额外参数">
              <Textarea id="p-options" className="font-mono text-xs" rows={5} value={form.options} onChange={(event) => set("options")(event.target.value)} aria-invalid={Boolean(problems.options) || undefined} />
            </Field>
            <Field label="能力（JSON）" htmlFor="p-cap" error={problems.capabilities} hint="json_schema、tools、vision、上下文长度">
              <Textarea id="p-cap" className="font-mono text-xs" rows={5} value={form.capabilities} onChange={(event) => set("capabilities")(event.target.value)} aria-invalid={Boolean(problems.capabilities) || undefined} />
            </Field>
          </form>
          {save.isError ? <InlineError className="mt-3">{save.error.message}</InlineError> : null}
        </DialogBody>
        <DialogFooter>
          {!creating && initial.updated_at ? (
            <span className="mr-auto text-xs text-muted-foreground">
              上次更新 <Time value={initial.updated_at} />
            </span>
          ) : null}
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" form="provider-form" loading={save.isPending}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
