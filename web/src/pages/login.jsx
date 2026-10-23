import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/misc";
import { InlineError, useDocumentTitle } from "@/components/common";
import { api } from "@/lib/api";
import { useAuthStatus } from "@/lib/session";

function safeNext(value) {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/login")) return "/";
  return value;
}

export default function LoginPage() {
  const status = useAuthStatus();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const setup = status.data?.setup_needed;
  useDocumentTitle(setup ? "初始化" : "登录");

  if (status.data?.signed_in) return <Navigate to={next} replace />;

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-[#171718] px-4 py-10">
      <div className="mb-6 flex items-center gap-2.5">
        <span className="flex size-9 items-center justify-center rounded-lg bg-primary text-sm font-bold text-white">cv</span>
        <div className="leading-tight">
          <p className="text-base font-semibold">cvgen</p>
          <p className="text-xs text-muted-foreground">视频生产控制台</p>
        </div>
      </div>
      <div className="w-full max-w-sm rounded-xl border bg-card p-6 shadow-sm">
        {status.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </div>
        ) : status.isError ? (
          <InlineError>连不上服务器：{status.error.message}</InlineError>
        ) : setup ? (
          <SetupForm next={next} />
        ) : (
          <LoginForm next={next} />
        )}
      </div>
      <p className="mt-6 text-xs text-muted-foreground">公司内部系统 · 账号由管理员分配</p>
    </div>
  );
}

function LoginForm({ next }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showReset, setShowReset] = useState(false);
  const login = useMutation({
    mutationFn: () => api.post("/api/auth/login", { username, password }, { quiet401: true }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["auth-status"] });
      navigate(next, { replace: true });
    },
    meta: { inline: true },
  });
  const submit = (event) => {
    event.preventDefault();
    if (!username.trim() || !password) return;
    login.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div>
        <h1 className="text-lg font-semibold">登录</h1>
        <p className="text-[13px] text-muted-foreground">用管理员给你的账号登录。</p>
      </div>
      <Field label="账号" htmlFor="username">
        <Input id="username" autoComplete="username" autoFocus value={username} onChange={(event) => setUsername(event.target.value)} aria-invalid={login.isError || undefined} />
      </Field>
      <Field label="密码" htmlFor="password">
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          aria-invalid={login.isError || undefined}
        />
      </Field>
      {login.isError ? <InlineError>{login.error.message}</InlineError> : null}
      <Button type="submit" className="w-full" loading={login.isPending} disabled={!username.trim() || !password}>
        登录
      </Button>
      <div className="text-center">
        <button type="button" className="text-[13px] text-muted-foreground hover:text-foreground" onClick={() => setShowReset((value) => !value)}>
          忘记密码？
        </button>
        {showReset ? (
          <div className="mt-2 rounded-md border border-[#4e4e4e] bg-[#222] px-3 py-2 text-left text-[13px] text-[#ddd]">
            <p className="flex items-center gap-1.5 font-medium">
              <KeyRound className="size-3.5" />
              找管理员重置
            </p>
            <p className="mt-1 text-muted-foreground">请管理员在服务器上运行：</p>
            <code className="mt-1 block break-all rounded bg-card px-2 py-1 text-xs">python -m server.manage reset-password &lt;账号&gt;</code>
          </div>
        ) : null}
      </div>
    </form>
  );
}

function SetupForm({ next }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [form, setForm] = useState({ username: "", display_name: "", password: "", confirm: "" });
  const [touched, setTouched] = useState(false);
  const problems = {
    username: !form.username.trim() ? "请填写账号" : "",
    password: form.password.length < 8 ? "密码至少 8 位" : "",
    confirm: form.confirm !== form.password ? "两次输入的密码不一致" : "",
  };
  const valid = !problems.username && !problems.password && !problems.confirm;
  const setup = useMutation({
    mutationFn: () => api.post("/api/auth/setup", { username: form.username.trim(), display_name: form.display_name.trim(), password: form.password }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["auth-status"] });
      navigate(next, { replace: true });
    },
    meta: { inline: true },
  });
  const update = (key) => (event) => setForm((value) => ({ ...value, [key]: event.target.value }));
  const submit = (event) => {
    event.preventDefault();
    setTouched(true);
    if (valid) setup.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold">
          <ShieldCheck className="size-5 text-primary" />
          初始化管理员
        </h1>
        <p className="text-[13px] text-muted-foreground">系统里还没有任何账号。创建第一个管理员账号，之后由管理员给其他人开账号。</p>
      </div>
      <Field label="账号" htmlFor="setup-username" required error={touched && problems.username}>
        <Input id="setup-username" autoFocus autoComplete="username" value={form.username} onChange={update("username")} aria-invalid={(touched && !!problems.username) || undefined} />
      </Field>
      <Field label="显示名" htmlFor="setup-name" hint="可选，默认和账号相同">
        <Input id="setup-name" value={form.display_name} onChange={update("display_name")} />
      </Field>
      <Field label="密码" htmlFor="setup-password" required error={touched && problems.password} hint="至少 8 位">
        <Input id="setup-password" type="password" autoComplete="new-password" value={form.password} onChange={update("password")} aria-invalid={(touched && !!problems.password) || undefined} />
      </Field>
      <Field label="再输一次密码" htmlFor="setup-confirm" required error={touched && problems.confirm}>
        <Input id="setup-confirm" type="password" autoComplete="new-password" value={form.confirm} onChange={update("confirm")} aria-invalid={(touched && !!problems.confirm) || undefined} />
      </Field>
      {setup.isError ? <InlineError>{setup.error.message}</InlineError> : null}
      <Button type="submit" className="w-full" loading={setup.isPending}>
        创建管理员并登录
      </Button>
    </form>
  );
}
