import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, Laptop, ShieldAlert, ShieldCheck, TerminalSquare } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/misc";
import { InlineError, KeyValues, Time, useDocumentTitle } from "@/components/common";
import { api } from "@/lib/api";
import { absoluteTime } from "@/lib/format";
import { ROLE } from "@/lib/labels";
import { useSession } from "@/lib/session";

function Shell({ children }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-[#171718] px-4 py-10">
      <Link to="/" className="mb-6 flex items-center gap-2.5">
        <span className="flex size-9 items-center justify-center rounded-lg bg-primary text-sm font-bold text-white">cv</span>
        <span className="text-base font-semibold">cvgen</span>
      </Link>
      <div className="w-full max-w-md rounded-xl border bg-card p-6 shadow-sm">{children}</div>
      <Link to="/" className="mt-5 text-[13px] text-muted-foreground hover:text-foreground">
        返回控制台
      </Link>
    </div>
  );
}

function StateBlock({ icon: Icon, tone, title, children }) {
  const tones = { green: "bg-[#14301f] text-[#81c784]", red: "bg-[#3a1717] text-[#ff6e6e]", gray: "bg-muted text-muted-foreground", amber: "bg-[#3a2a12] text-[#ffa931]" };
  return (
    <div className="flex flex-col items-center py-2 text-center">
      <span className={`mb-3 flex size-11 items-center justify-center rounded-full ${tones[tone]}`}>
        <Icon className="size-5" />
      </span>
      <h1 className="text-lg font-semibold">{title}</h1>
      <div className="mt-1.5 text-[13px] text-muted-foreground">{children}</div>
    </div>
  );
}

function CodeEntry() {
  const navigate = useNavigate();
  const [code, setCode] = useState("");
  const cleaned = code.toUpperCase().replace(/[^A-Z0-9]/g, "");
  return (
    <Shell>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (cleaned.length === 8) navigate(`/approve/${cleaned.slice(0, 4)}-${cleaned.slice(4)}`);
        }}
      >
        <div>
          <h1 className="text-lg font-semibold">批准 agent 设备</h1>
          <p className="text-[13px] text-muted-foreground">输入终端里 cvgen login 显示的 8 位设备码。</p>
        </div>
        <Field label="设备码" htmlFor="code" hint="例如 ABCD-EFGH">
          <Input id="code" autoFocus value={code} onChange={(event) => setCode(event.target.value)} className="font-mono uppercase tracking-widest" placeholder="XXXX-XXXX" />
        </Field>
        <Button type="submit" className="w-full" disabled={cleaned.length !== 8}>
          查看设备
        </Button>
      </form>
    </Shell>
  );
}

export default function ApprovePage() {
  const { code } = useParams();
  useDocumentTitle("批准设备");
  if (!code) return <CodeEntry />;
  return <ApproveCode code={code} />;
}

function ApproveCode({ code }) {
  const { me } = useSession();
  const device = useQuery({
    queryKey: ["device-code", code],
    queryFn: () => api.get(`/api/devices/code/${encodeURIComponent(code)}`),
    retry: false,
    refetchOnWindowFocus: false,
  });
  const approve = useMutation({
    mutationFn: () => api.post(`/api/devices/code/${encodeURIComponent(code)}/approve`),
    meta: { inline: true },
  });

  if (!device.data && device.isLoading) {
    return (
      <Shell>
        <div className="space-y-3">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      </Shell>
    );
  }

  if (approve.isSuccess) {
    return (
      <Shell>
        <StateBlock icon={CheckCircle2} tone="green" title="已批准">
          <p>回到终端，cvgen 会在几秒内自动完成登录。</p>
          <p className="mt-1">这台设备以你的名义工作，可以在「设置 → 设备」里随时吊销。</p>
        </StateBlock>
      </Shell>
    );
  }

  if (device.isError) {
    const status = device.error.status;
    return (
      <Shell>
        {status === 410 ? (
          <StateBlock icon={Clock} tone="amber" title="设备码已过期">
            设备码 10 分钟内有效。请在终端重新运行 <code className="rounded bg-muted px-1">cvgen login</code>，再打开新链接。
          </StateBlock>
        ) : status === 404 ? (
          <StateBlock icon={ShieldAlert} tone="red" title="没有这个设备码">
            请核对链接里的设备码 <code className="rounded bg-muted px-1">{code}</code> 是否和终端显示的一致。
          </StateBlock>
        ) : status === 403 ? (
          <StateBlock icon={ShieldAlert} tone="red" title="没有权限批准设备">
            你的角色是 {ROLE[me.role] || me.role}，请联系管理员。
          </StateBlock>
        ) : (
          <InlineError>{device.error.message}</InlineError>
        )}
      </Shell>
    );
  }

  const data = device.data;
  if (data.status !== "pending") {
    const text = {
      approved: ["这个设备码已经用过了", "它已经被批准，不能再批准一次。如果不是你批准的，请到「设置 → 设备」吊销。"],
      revoked: ["这台设备已被吊销", "如需重新接入，请在终端重新运行 cvgen login。"],
      expired: ["设备码已过期", "请在终端重新运行 cvgen login。"],
    }[data.status] || ["设备码不可用", `当前状态：${data.status}`];
    return (
      <Shell>
        <StateBlock icon={data.status === "approved" ? ShieldCheck : Clock} tone="gray" title={text[0]}>
          {text[1]}
        </StateBlock>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="space-y-4">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            <TerminalSquare className="size-5" />
          </span>
          <div>
            <h1 className="text-lg font-semibold">批准 agent 设备接入</h1>
            <p className="text-[13px] text-muted-foreground">批准后，这台设备上的 cvgen 以你的名义操作探索任务，花费计入你名下。</p>
          </div>
        </div>
        <div className="rounded-lg border bg-[#222] p-4">
          <p className="mb-3 text-center font-mono text-2xl font-semibold tracking-[0.2em]">{data.user_code}</p>
          <KeyValues
            items={[
              ["设备名", <span className="inline-flex items-center gap-1.5"><Laptop className="size-3.5 text-muted-foreground" />{data.name || "未命名"}</span>],
              ["客户端版本", data.client_version || "未知"],
              ["申请时间", <Time value={data.created_at} />],
              ["有效期至", <span className="tnum">{absoluteTime(data.expires_at)}</span>],
            ]}
          />
        </div>
        <p className="text-[13px] text-muted-foreground">请确认终端里显示的设备码与上面一致。不认识的申请不要批准。</p>
        {approve.isError ? <InlineError>{approve.error.message}</InlineError> : null}
        <Button className="w-full" onClick={() => approve.mutate()} loading={approve.isPending}>
          <ShieldCheck />
          批准这台设备
        </Button>
      </div>
    </Shell>
  );
}
