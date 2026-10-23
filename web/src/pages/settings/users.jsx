import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, UserRound, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Switch, TBody, THead, Table } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { EmptyState, InlineError, QueryView, SkeletonRows, Time, useConfirm } from "@/components/common";
import { api } from "@/lib/api";
import { ROLE } from "@/lib/labels";
import { useSession } from "@/lib/session";

const ROLE_OPTIONS = [
  { value: "producer", label: "制作 — 发起运行、审片、下载" },
  { value: "reviewer", label: "审计员 — 审批闸门、发布工作流、留意见" },
  { value: "admin", label: "管理员 — 全部权限" },
];

export default function UsersTab() {
  const { me } = useSession();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get("/api/admin/users") });
  const [editing, setEditing] = useState(null);
  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[13px] text-muted-foreground">停用账号或重置密码后，该账号所有登录会立即失效。</p>
        <Button size="sm" onClick={() => setEditing({})}>
          <Plus />
          新建账号
        </Button>
      </div>
      <QueryView query={users} skeleton={<SkeletonRows rows={3} />}>
        {(data) =>
          data.items.length ? (
            <Card className="overflow-hidden">
              <Table>
                <THead>
                  <tr>
                    <th>账号</th>
                    <th>角色</th>
                    <th>状态</th>
                    <th className="hidden sm:table-cell">创建</th>
                    <th />
                  </tr>
                </THead>
                <TBody>
                  {data.items.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <div className="flex items-center gap-2">
                          <span className="flex size-7 items-center justify-center rounded-full bg-[#123044] text-xs font-semibold text-[#64b5f6]">{user.display_name.slice(0, 1).toUpperCase()}</span>
                          <div>
                            <div className="font-medium">
                              {user.display_name}
                              {user.id === me.id ? <span className="ml-1.5 text-xs font-normal text-muted-foreground">（你）</span> : null}
                            </div>
                            <div className="text-xs text-muted-foreground">{user.username}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <Badge tone={user.role === "admin" ? "violet" : user.role === "reviewer" ? "blue" : "gray"}>{ROLE[user.role] || user.role}</Badge>
                      </td>
                      <td>{user.disabled ? <Badge tone="red">已停用</Badge> : <Badge tone="green">正常</Badge>}</td>
                      <td className="hidden text-[13px] text-muted-foreground sm:table-cell">
                        <Time value={user.created_at} />
                      </td>
                      <td className="text-right">
                        <Button size="xs" variant="outline" onClick={() => setEditing(user)}>
                          <Pencil />
                          编辑
                        </Button>
                      </td>
                    </tr>
                  ))}
                </TBody>
              </Table>
            </Card>
          ) : (
            <EmptyState icon={Users} title="没有账号" />
          )
        }
      </QueryView>
      {editing ? <UserDialog user={editing} self={editing.id === me.id} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}

function UserDialog({ user, self, onClose }) {
  const client = useQueryClient();
  const confirm = useConfirm();
  const creating = !user.id;
  const [form, setForm] = useState({ username: user.username || "", display_name: user.display_name || "", role: user.role || "producer", password: "", disabled: Boolean(user.disabled) });
  const [touched, setTouched] = useState(false);
  const set = (key) => (value) => setForm((current) => ({ ...current, [key]: value }));
  const problems = {
    username: creating && !form.username.trim() ? "请填写账号" : "",
    password: creating ? (form.password.length < 8 ? "密码至少 8 位" : "") : form.password && form.password.length < 8 ? "密码至少 8 位" : "",
  };
  const valid = !problems.username && !problems.password;
  const save = useMutation({
    mutationFn: () =>
      creating
        ? api.post("/api/admin/users", { username: form.username.trim(), display_name: form.display_name.trim(), role: form.role, password: form.password })
        : api.patch(`/api/admin/users/${user.id}`, {
            username: user.username,
            display_name: form.display_name.trim(),
            role: form.role,
            disabled: form.disabled,
            password: form.password,
          }),
    onSuccess: () => {
      toast.success(creating ? `已创建账号 ${form.username}` : "已保存", form.password && !creating ? "新密码已生效，旧登录已失效" : undefined);
      client.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    meta: { inline: true },
  });
  const submit = (event) => {
    event.preventDefault();
    setTouched(true);
    if (!valid) return;
    if (!creating && form.disabled && !user.disabled) {
      confirm({
        title: `停用 ${user.display_name}？`,
        description: "停用后此账号立即退出所有登录，不能再登录。它批准的设备不受影响，需要单独吊销。",
        confirmText: "停用",
        danger: true,
      }).then((ok) => ok && save.mutate());
      return;
    }
    save.mutate();
  };
  return (
    <Dialog open onOpenChange={(open) => (!open ? onClose() : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserRound className="size-4" />
            {creating ? "新建账号" : `编辑 ${user.display_name}`}
          </DialogTitle>
          {!creating ? <DialogDescription>账号 {user.username}</DialogDescription> : null}
        </DialogHeader>
        <DialogBody>
          <form id="user-form" className="grid gap-4" onSubmit={submit}>
            {creating ? (
              <Field label="账号" htmlFor="u-name" required error={touched && problems.username}>
                <Input id="u-name" autoComplete="off" value={form.username} onChange={(event) => set("username")(event.target.value)} aria-invalid={(touched && !!problems.username) || undefined} />
              </Field>
            ) : null}
            <Field label="显示名" htmlFor="u-display">
              <Input id="u-display" value={form.display_name} onChange={(event) => set("display_name")(event.target.value)} />
            </Field>
            <Field label="角色" htmlFor="u-role" hint={self ? "不能降低自己的管理员角色" : undefined}>
              <Select id="u-role" value={form.role} disabled={self} onChange={(event) => set("role")(event.target.value)} options={ROLE_OPTIONS} />
            </Field>
            <Field
              label={creating ? "初始密码" : "重置密码"}
              htmlFor="u-password"
              required={creating}
              error={touched && problems.password}
              hint={creating ? "至少 8 位，请通过安全渠道告诉对方" : "留空表示不修改"}
            >
              <Input id="u-password" type="password" autoComplete="new-password" value={form.password} onChange={(event) => set("password")(event.target.value)} aria-invalid={(touched && !!problems.password) || undefined} />
            </Field>
            {!creating && !self ? (
              <label className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
                <span>
                  <span className="block text-[13px] font-medium">停用账号</span>
                  <span className="block text-xs text-muted-foreground">停用后不能登录</span>
                </span>
                <Switch checked={form.disabled} onCheckedChange={set("disabled")} />
              </label>
            ) : null}
          </form>
          {save.isError ? <InlineError className="mt-3">{save.error.message}</InlineError> : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" form="user-form" loading={save.isPending}>
            {creating ? "创建" : "保存"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
