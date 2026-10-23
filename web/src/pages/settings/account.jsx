import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { toast } from "@/components/ui/toast";
import { InlineError, KeyValues } from "@/components/common";
import { api } from "@/lib/api";
import { ROLE } from "@/lib/labels";
import { useSession } from "@/lib/session";

export default function AccountTab() {
  const { me } = useSession();
  const [form, setForm] = useState({ password: "", next: "", confirm: "" });
  const [touched, setTouched] = useState(false);
  const set = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));
  const problems = {
    password: !form.password ? "请输入当前密码" : "",
    next: form.next.length < 8 ? "新密码至少 8 位" : form.next === form.password ? "新密码不能和当前密码相同" : "",
    confirm: form.confirm !== form.next ? "两次输入的新密码不一致" : "",
  };
  const valid = Object.values(problems).every((value) => !value);
  const change = useMutation({
    mutationFn: () => api.post("/api/auth/password", { password: form.password, next_password: form.next }, { quiet401: true }),
    onSuccess: (result) => {
      toast.success("密码已更新", result?.message);
      setForm({ password: "", next: "", confirm: "" });
      setTouched(false);
    },
    meta: { inline: true },
  });
  const show = (key) => touched && problems[key];
  return (
    <div className="grid max-w-4xl gap-5 lg:grid-cols-2">
      <Card className="h-fit">
        <CardHeader>
          <CardTitle>账号信息</CardTitle>
        </CardHeader>
        <CardContent>
          <KeyValues
            items={[
              ["名称", me.name],
              ["角色", ROLE[me.role] || me.role],
              ["编号", <code className="text-xs">{me.id}</code>],
              ["权限", <span className="text-xs text-muted-foreground">{(me.perms || []).length} 项</span>],
            ]}
          />
        </CardContent>
      </Card>
      <Card>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setTouched(true);
            if (valid) change.mutate();
          }}
          noValidate
        >
          <CardHeader>
            <CardTitle>修改密码</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field label="当前密码" htmlFor="pw-current" error={show("password")}>
              <Input id="pw-current" type="password" autoComplete="current-password" value={form.password} onChange={set("password")} aria-invalid={Boolean(show("password")) || undefined} />
            </Field>
            <Field label="新密码" htmlFor="pw-next" error={show("next")} hint="至少 8 位">
              <Input id="pw-next" type="password" autoComplete="new-password" value={form.next} onChange={set("next")} aria-invalid={Boolean(show("next")) || undefined} />
            </Field>
            <Field label="再输一次新密码" htmlFor="pw-confirm" error={show("confirm")}>
              <Input id="pw-confirm" type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} aria-invalid={Boolean(show("confirm")) || undefined} />
            </Field>
            {change.isError ? <InlineError>{change.error.message}</InlineError> : null}
            <p className="text-xs text-muted-foreground">修改后，你在其他浏览器上的登录会失效。</p>
          </CardContent>
          <CardFooter>
            <Button type="submit" loading={change.isPending}>
              更新密码
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
