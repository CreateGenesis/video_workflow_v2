import { useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, Download, Laptop, PlugZap, Rocket, Workflow, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyButton } from "@/components/common";
import { api, qs } from "@/lib/api";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const HIDE_KEY = "cvgen.getting-started.hidden";

/**
 * First-run checklist: providers → an agent device → a published workflow → the first run.
 * Each step links to the page that completes it. Hidden once everything is done (or dismissed).
 */
export function GettingStarted() {
  const { can, workspaceId } = useSession();
  const [hidden, setHidden] = useState(() => localStorage.getItem(HIDE_KEY) === "1");
  const isAdmin = can("admin");
  const providers = useQuery({ queryKey: ["providers"], queryFn: () => api.get("/api/admin/providers"), enabled: can("queue:read") });
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get("/api/devices") });
  const workflows = useQuery({
    queryKey: ["workflows", workspaceId],
    queryFn: () => api.get(`/api/workflows${qs({ workspace_id: workspaceId })}`),
    enabled: Boolean(workspaceId),
  });
  const runs = useQuery({
    queryKey: ["runs", "any", workspaceId],
    queryFn: () => api.get(`/api/runs${qs({ workspace_id: workspaceId, limit: 1 })}`),
    enabled: can("runs:read") && Boolean(workspaceId),
  });
  if (hidden) return null;
  const waiting =
    (!providers.data && (providers.isLoading || providers.isPending)) ||
    (!devices.data && (devices.isLoading || devices.isPending)) ||
    (!workflows.data && (workflows.isLoading || workflows.isPending));
  if (waiting) return null;

  const kinds = new Set((providers.data?.items || []).filter((item) => item.enabled).map((item) => item.kind));
  const missingKinds = [["llm", "大模型"], ["image", "生图"], ["video", "视频"]].filter(([kind]) => !kinds.has(kind)).map(([, label]) => label);
  const hasDevice = (devices.data?.items || []).some((item) => item.status === "approved");
  const published = (workflows.data?.items || []).some((item) => item.published_version);
  const drafts = (workflows.data?.items || []).length;
  const hasRun = (runs.data?.items || []).length > 0;
  const steps = [
    {
      done: missingKinds.length === 0,
      icon: PlugZap,
      title: "登记供应商",
      text: missingKinds.length ? `还缺：${missingKinds.join("、")}。大模型把灵感写成分镜，生图出关键帧，视频走 AutoDL 或自部署 ComfyUI。` : "大模型、生图、视频都已登记。",
      action: isAdmin ? { to: "/settings?tab=providers", label: "去设置供应商" } : null,
    },
    {
      done: hasDevice,
      icon: Laptop,
      title: "接入 agent 的 cvgen",
      text: "下载 cvgen，在 agent 所在的机器上运行下面的命令；终端会给出一个链接，登录网页打开它批准。",
      command: `cvgen login --base ${window.location.origin}`,
      action: { to: "/settings?tab=tools", label: "下载 cvgen", icon: Download },
    },
    {
      done: published,
      icon: Workflow,
      title: "准备一个已发布的工作流",
      text: drafts
        ? "已有草稿。打开版本页修正校验问题（例如把节点换成你登记的供应商），审计员发布后就能用来出片。"
        : "agent 探索定型后提交草稿；也可以导入 JSON，或由管理员载入示例再改成自己的供应商。",
      action: { to: "/workflows", label: drafts ? "查看草稿" : "去工作流" },
    },
    {
      done: hasRun,
      icon: Rocket,
      title: "发起第一个运行",
      text: "选择已发布的工作流，填写灵感，确认花费后排队执行。",
      action: published && can("runs:create") ? { to: "/runs/new", label: "发起运行" } : null,
    },
  ];
  const remaining = steps.filter((step) => !step.done).length;
  if (!remaining) return null;
  const dismiss = () => {
    localStorage.setItem(HIDE_KEY, "1");
    setHidden(true);
  };
  return (
    <Card className="border-[#0b8ce9]/40">
      <CardHeader>
        <div>
          <CardTitle>开始使用</CardTitle>
          <p className="text-[13px] text-muted-foreground">还有 {remaining} 步，完成后就能填灵感一键出片。</p>
        </div>
        <Button size="icon-sm" variant="ghost" aria-label="隐藏开始使用" title="隐藏" onClick={dismiss}>
          <X />
        </Button>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {steps.map((step, index) => {
          const Icon = step.icon;
          const ActionIcon = step.action?.icon;
          return (
            <div key={step.title} className={cn("flex flex-col gap-2 rounded-lg border p-3", step.done ? "bg-[#1f2a1f] border-[#2f4a2f]" : "bg-[#222]")}>
              <div className="flex items-center gap-2">
                {step.done ? <CheckCircle2 className="size-4 text-[#81c784]" /> : <Circle className="size-4 text-muted-foreground" />}
                <span className="tnum text-xs text-muted-foreground">{index + 1}</span>
                <Icon className="size-4 text-muted-foreground" />
                <span className="text-sm font-medium">{step.title}</span>
              </div>
              <p className="flex-1 text-[13px] leading-relaxed text-muted-foreground">{step.text}</p>
              {step.command && !step.done ? (
                <div className="flex items-center gap-2 rounded border bg-[#171718] px-2 py-1">
                  <code className="min-w-0 flex-1 truncate text-xs">{step.command}</code>
                  <CopyButton value={step.command} />
                </div>
              ) : null}
              {step.action && !step.done ? (
                <Button asChild size="sm" variant={index === steps.findIndex((item) => !item.done) ? "default" : "outline"} className="w-fit">
                  <Link to={step.action.to}>
                    {ActionIcon ? <ActionIcon /> : null}
                    {step.action.label}
                  </Link>
                </Button>
              ) : null}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
