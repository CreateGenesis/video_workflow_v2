import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, KeyRound, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { TBody, THead, Table } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { CopyButton, EmptyState, InlineError, Money, Notice, QueryView, SkeletonRows, Time, useConfirm } from "@/components/common";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const SCOPES = [
  { value: "runs:write", label: "发起运行", hint: "发起运行和批量、上传输入素材" },
  { value: "runs:read", label: "查看运行", hint: "查看运行状态和产物" },
  { value: "assets:write", label: "上传素材", hint: "只上传文件" },
];

export default function KeysTab() {
  const { workspaces } = useSession();
  const client = useQueryClient();
  const confirm = useConfirm();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => api.get("/api/admin/keys") });
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState(null);
  const revoke = useMutation({
    mutationFn: (id) => api.post(`/api/admin/keys/${id}/revoke`),
    onSuccess: () => {
      toast.success("密钥已吊销", "使用它的服务会立即收到 401");
      client.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });
  const workspaceName = (id) => workspaces.find((item) => item.id === id)?.name || id;
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          给其他服务调用 <code className="rounded bg-muted px-1">/v1</code> 接口用。每个密钥绑定一个工作区，有自己的权限范围、限流和月预算。
        </p>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus />
          新建密钥
        </Button>
      </div>
      <QueryView query={keys} skeleton={<SkeletonRows rows={3} />}>
        {(data) =>
          data.items.length ? (
            <Card className="overflow-hidden">
              <Table>
                <THead>
                  <tr>
                    <th>名称</th>
                    <th>权限范围</th>
                    <th className="hidden md:table-cell">工作区</th>
                    <th className="hidden lg:table-cell">限流 / 月预算</th>
                    <th className="hidden sm:table-cell">最近使用</th>
                    <th />
                  </tr>
                </THead>
                <TBody>
                  {data.items.map((key) => (
                    <tr key={key.id} className={cn(key.revoked_at && "opacity-60")}>
                      <td>
                        <div className="font-medium">{key.name}</div>
                        <code className="text-xs text-muted-foreground">{key.prefix}…</code>
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1">
                          {(key.scopes || []).map((scope) => (
                            <Badge key={scope}>{SCOPES.find((item) => item.value === scope)?.label || scope}</Badge>
                          ))}
                        </div>
                      </td>
                      <td className="hidden text-[13px] md:table-cell">{workspaceName(key.workspace_id)}</td>
                      <td className="tnum hidden text-[13px] lg:table-cell">
                        {key.rate_per_minute} 次/分 · {key.monthly_budget_yuan ? <Money value={key.monthly_budget_yuan} digits={2} /> : "不限"}
                      </td>
                      <td className="hidden text-[13px] text-muted-foreground sm:table-cell">{key.last_used_at ? <Time value={key.last_used_at} /> : "从未使用"}</td>
                      <td className="text-right">
                        {key.revoked_at ? (
                          <Badge tone="red">已吊销</Badge>
                        ) : (
                          <Button
                            size="xs"
                            variant="destructive-outline"
                            onClick={() =>
                              confirm({
                                title: `吊销密钥「${key.name}」？`,
                                description: "吊销后使用这个密钥的服务会立即失败。这个操作不能撤销，只能新建一个。",
                                confirmText: "吊销",
                                danger: true,
                                action: () => revoke.mutateAsync(key.id),
                              })
                            }
                          >
                            <Ban />
                            吊销
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </TBody>
              </Table>
            </Card>
          ) : (
            <EmptyState icon={KeyRound} title="还没有 API 密钥" description="需要让其他服务自动发起运行时，在这里创建一个密钥。" />
          )
        }
      </QueryView>
      {creating ? (
        <CreateKeyDialog
          onClose={() => setCreating(false)}
          onCreated={(result) => {
            setCreating(false);
            setCreated(result);
          }}
        />
      ) : null}
      <Dialog open={Boolean(created)} onOpenChange={(open) => (!open ? setCreated(null) : null)}>
        {created ? (
          <DialogContent>
            <DialogHeader>
              <DialogTitle>密钥已创建</DialogTitle>
              <DialogDescription>只显示这一次。关闭后无法再查看，请立即复制保存。</DialogDescription>
            </DialogHeader>
            <DialogBody className="space-y-3">
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">API 密钥（调用时放在请求头 Authorization: Bearer …）</span>
                  <CopyButton value={created.key} label="复制" />
                </div>
                <div className="break-all rounded-md border bg-[#222] p-3 font-mono text-[13px]">{created.key}</div>
              </div>
              {created.webhook_secret ? (
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="text-xs font-medium text-muted-foreground">回调签名密钥（验证 X-CVGEN-Signature 用）</span>
                    <CopyButton value={created.webhook_secret} label="复制" />
                  </div>
                  <div className="break-all rounded-md border bg-[#222] p-3 font-mono text-[13px]">{created.webhook_secret}</div>
                </div>
              ) : null}
              <Notice tone="warn">两个值都只显示这一次。回调的签名是 HMAC-SHA256(回调签名密钥, "时间戳.请求体")，时间戳在 X-CVGEN-Timestamp 头里。</Notice>
            </DialogBody>
            <DialogFooter>
              <CopyButton value={`CVGEN_API_KEY=${created.key}\nCVGEN_WEBHOOK_SECRET=${created.webhook_secret || ""}`} label="复制为环境变量" size="default" variant="default" />
              <Button variant="outline" onClick={() => setCreated(null)}>
                我已保存
              </Button>
            </DialogFooter>
          </DialogContent>
        ) : null}
      </Dialog>
    </div>
  );
}

function CreateKeyDialog({ onClose, onCreated }) {
  const { workspaces, workspaceId } = useSession();
  const client = useQueryClient();
  const [form, setForm] = useState({ name: "", workspace_id: workspaceId, scopes: ["runs:write", "runs:read"], rate: "60", budget: "" });
  const [touched, setTouched] = useState(false);
  const set = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));
  const problems = {
    name: !form.name.trim() ? "请填写名称" : "",
    scopes: !form.scopes.length ? "至少选一个权限范围" : "",
    rate: !/^\d+$/.test(form.rate) ? "请输入整数" : "",
    budget: form.budget && !(Number(form.budget) >= 0) ? "请输入金额" : "",
  };
  const valid = Object.values(problems).every((value) => !value);
  const create = useMutation({
    mutationFn: () =>
      api.post("/api/admin/keys", {
        name: form.name.trim(),
        workspace_id: form.workspace_id,
        scopes: form.scopes,
        rate_per_minute: Number(form.rate),
        monthly_budget_yuan: form.budget ? Number(form.budget) : null,
      }),
    onSuccess: (result) => {
      client.invalidateQueries({ queryKey: ["api-keys"] });
      onCreated(result);
    },
    meta: { inline: true },
  });
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建 API 密钥</DialogTitle>
        </DialogHeader>
        <DialogBody>
          <form
            id="key-form"
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              setTouched(true);
              if (valid) create.mutate();
            }}
          >
            <Field label="名称" htmlFor="k-name" required error={touched && problems.name} hint="写清是哪个服务在用，例如 电商后台">
              <Input id="k-name" value={form.name} onChange={(event) => set("name")(event.target.value)} aria-invalid={(touched && !!problems.name) || undefined} />
            </Field>
            <Field label="工作区" htmlFor="k-ws">
              <Select id="k-ws" value={form.workspace_id} onChange={(event) => set("workspace_id")(event.target.value)} options={workspaces.map((item) => ({ value: item.id, label: item.name }))} />
            </Field>
            <Field label="权限范围" required error={touched && problems.scopes}>
              <div className="grid gap-1.5">
                {SCOPES.map((scope) => (
                  <label key={scope.value} className="flex items-start gap-2 rounded-md border px-3 py-2">
                    <input
                      type="checkbox"
                      className="mt-1 accent-[#2558d6]"
                      checked={form.scopes.includes(scope.value)}
                      onChange={(event) => set("scopes")(event.target.checked ? [...form.scopes, scope.value] : form.scopes.filter((item) => item !== scope.value))}
                    />
                    <span>
                      <span className="block text-[13px] font-medium">
                        {scope.label} <code className="text-xs font-normal text-muted-foreground">{scope.value}</code>
                      </span>
                      <span className="block text-xs text-muted-foreground">{scope.hint}</span>
                    </span>
                  </label>
                ))}
              </div>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="每分钟请求上限" htmlFor="k-rate" error={touched && problems.rate}>
                <Input id="k-rate" type="number" min={0} className="tnum" value={form.rate} onChange={(event) => set("rate")(event.target.value)} />
              </Field>
              <Field label="月预算（元）" htmlFor="k-budget" hint="留空不限" error={touched && problems.budget}>
                <Input id="k-budget" type="number" min={0} step="0.01" className="tnum" value={form.budget} onChange={(event) => set("budget")(event.target.value)} />
              </Field>
            </div>
          </form>
          {create.isError ? <InlineError className="mt-3">{create.error.message}</InlineError> : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" form="key-form" loading={create.isPending}>
            创建
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
