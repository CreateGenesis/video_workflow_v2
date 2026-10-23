import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Laptop, Pencil, ShieldPlus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { TBody, THead, Table } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { EmptyState, InlineError, Money, QueryView, SkeletonRows, Time, useConfirm } from "@/components/common";
import { api } from "@/lib/api";
import { DEVICE_STATUS, statusOf } from "@/lib/labels";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

export default function DevicesTab() {
  const { can } = useSession();
  const client = useQueryClient();
  const confirm = useConfirm();
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get("/api/devices") });
  const [editing, setEditing] = useState(null);
  const revoke = useMutation({
    mutationFn: (id) => api.post(`/api/devices/${id}/revoke`),
    onSuccess: () => {
      toast.success("设备已吊销", "这台设备上的 cvgen 需要重新登录");
      client.invalidateQueries({ queryKey: ["devices"] });
    },
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">
          {can("devices:manage") ? "所有人批准的 agent 设备。" : "你批准的 agent 设备。"}设备以批准人的名义执行探索任务，受每日预算约束。
        </p>
        <Button asChild size="sm" variant="outline">
          <Link to="/approve">
            <ShieldPlus />
            输入设备码批准
          </Link>
        </Button>
      </div>
      <QueryView query={devices} skeleton={<SkeletonRows rows={3} />}>
        {(data) =>
          data.items.length ? (
            <Card className="overflow-hidden">
              <Table>
                <THead>
                  <tr>
                    <th>设备</th>
                    <th>状态</th>
                    {can("devices:manage") ? <th className="hidden md:table-cell">归属</th> : null}
                    <th className="hidden sm:table-cell">每日预算</th>
                    <th className="hidden lg:table-cell">最近在线</th>
                    <th />
                  </tr>
                </THead>
                <TBody>
                  {data.items.map((device) => {
                    const status = statusOf(DEVICE_STATUS, device.status);
                    return (
                      <tr key={device.id} className={cn(device.status === "revoked" && "opacity-60")}>
                        <td>
                          <div className="flex items-center gap-2">
                            <Laptop className="size-4 text-muted-foreground" />
                            <div>
                              <div className="font-medium">{device.name || "未命名设备"}</div>
                              <div className="text-xs text-muted-foreground">
                                {device.user_code} · {device.client_version || "版本未知"}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <div className="flex flex-wrap gap-1">
                            <Badge tone={status.tone}>{status.label}</Badge>
                            {device.status === "approved" ? device.online ? <Badge tone="green" dot>在线</Badge> : <Badge dot>离线</Badge> : null}
                          </div>
                        </td>
                        {can("devices:manage") ? <td className="hidden text-[13px] md:table-cell">{device.username || "—"}</td> : null}
                        <td className="hidden text-[13px] sm:table-cell">{device.daily_budget_yuan ? <Money value={device.daily_budget_yuan} digits={2} /> : <span className="text-muted-foreground">默认</span>}</td>
                        <td className="hidden text-[13px] text-muted-foreground lg:table-cell">{device.last_seen_at ? <Time value={device.last_seen_at} /> : "—"}</td>
                        <td className="text-right">
                          {device.status === "approved" ? (
                            <div className="flex justify-end gap-1">
                              <Button size="xs" variant="outline" onClick={() => setEditing(device)}>
                                <Pencil />
                                编辑
                              </Button>
                              <Button
                                size="xs"
                                variant="destructive-outline"
                                onClick={() =>
                                  confirm({
                                    title: `吊销设备「${device.name || device.user_code}」？`,
                                    description: "这台设备上的 cvgen 会立即失去访问权限。已经排队的任务不受影响。",
                                    confirmText: "吊销",
                                    danger: true,
                                    action: () => revoke.mutateAsync(device.id),
                                  })
                                }
                              >
                                <Ban />
                                吊销
                              </Button>
                            </div>
                          ) : null}
                        </td>
                      </tr>
                    );
                  })}
                </TBody>
              </Table>
            </Card>
          ) : (
            <EmptyState
              icon={Laptop}
              title="还没有设备"
              description="在电脑上运行 cvgen login，终端会显示一个批准链接；用浏览器打开并批准即可。"
              action={
                <Button asChild size="sm" variant="outline">
                  <Link to="/settings?tab=tools">下载 cvgen</Link>
                </Button>
              }
            />
          )
        }
      </QueryView>
      {editing ? <DeviceDialog device={editing} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}

function DeviceDialog({ device, onClose }) {
  const { can } = useSession();
  const client = useQueryClient();
  const [name, setName] = useState(device.name || "");
  const [budget, setBudget] = useState(device.daily_budget_yuan ? String(device.daily_budget_yuan) : "");
  const bad = budget && !(Number(budget) >= 0);
  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim() || null };
      if (can("devices:manage")) body.daily_budget_yuan = budget ? Number(budget) : null;
      return api.patch(`/api/devices/${device.id}`, body);
    },
    onSuccess: () => {
      toast.success("已保存");
      client.invalidateQueries({ queryKey: ["devices"] });
      onClose();
    },
    meta: { inline: true },
  });
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>编辑设备</DialogTitle>
          <DialogDescription>{device.user_code}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <Field label="设备名" htmlFor="d-name">
            <Input id="d-name" value={name} onChange={(event) => setName(event.target.value)} />
          </Field>
          <Field
            label="每日预算（元）"
            htmlFor="d-budget"
            hint={can("devices:manage") ? "留空使用系统默认。超出后这台设备当天不能再发起付费任务。" : "设备预算由审计员或管理员设置"}
            error={bad ? "请输入金额" : ""}
          >
            <Input id="d-budget" type="number" min={0} step="0.01" className="tnum" value={budget} disabled={!can("devices:manage")} onChange={(event) => setBudget(event.target.value)} />
          </Field>
          {save.isError ? <InlineError>{save.error.message}</InlineError> : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button onClick={() => save.mutate()} disabled={Boolean(bad)} loading={save.isPending}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
