import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/label";
import { Switch } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { Notice, QueryView, SkeletonRows, useConfirm } from "@/components/common";
import { api } from "@/lib/api";

export default function SystemTab() {
  const settings = useQuery({ queryKey: ["admin-settings"], queryFn: () => api.get("/api/admin/settings") });
  return (
    <QueryView query={settings} skeleton={<SkeletonRows rows={2} />}>
      {(data) => <SystemForm data={data} />}
    </QueryView>
  );
}

function SystemForm({ data }) {
  const client = useQueryClient();
  const confirm = useConfirm();
  const [passthrough, setPassthrough] = useState(Boolean(data.ffmpeg_passthrough));
  const [threshold, setThreshold] = useState(String(data.approval_threshold_yuan ?? ""));
  useEffect(() => {
    setPassthrough(Boolean(data.ffmpeg_passthrough));
    setThreshold(String(data.approval_threshold_yuan ?? ""));
  }, [data]);
  const bad = threshold === "" || !(Number(threshold) >= 0);
  const dirty = passthrough !== Boolean(data.ffmpeg_passthrough) || Number(threshold) !== Number(data.approval_threshold_yuan);
  const save = useMutation({
    mutationFn: () => api.patch("/api/admin/settings", { ffmpeg_passthrough: passthrough, approval_threshold_yuan: Number(threshold) }),
    onSuccess: () => {
      toast.success("系统设置已保存");
      client.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });
  const submit = () => {
    if (passthrough && !data.ffmpeg_passthrough) {
      confirm({
        title: "开启 ffmpeg 透传？",
        description: "agent 可以向服务器提交任意 ffmpeg 参数（限定在任务临时目录内执行）。只在确实需要时开启。",
        confirmText: "开启并保存",
        danger: true,
        action: () => save.mutateAsync(),
      });
    } else save.mutate();
  };
  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>系统开关</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium">允许 ffmpeg 透传</p>
            <p className="text-[13px] text-muted-foreground">开启后，agent 可以提交自定义 ffmpeg 参数的剪辑任务。参数在任务临时目录内执行。</p>
          </div>
          <Switch checked={passthrough} onCheckedChange={setPassthrough} aria-label="允许 ffmpeg 透传" />
        </div>
        {passthrough ? (
          <Notice tone="warn" icon={AlertTriangle}>
            透传已开启：请确认只有可信的设备能访问。
          </Notice>
        ) : null}
        <Field
          label="探索任务审批阈值（元）"
          htmlFor="threshold"
          hint="agent 设备发起的单个任务预估花费超过这个金额时，需要审计员在网页上批准后才执行。填 0 表示不需要审批。"
          error={bad ? "请输入不小于 0 的金额" : ""}
        >
          <Input id="threshold" type="number" min={0} step="1" className="tnum max-w-40" value={threshold} onChange={(event) => setThreshold(event.target.value)} aria-invalid={bad || undefined} />
        </Field>
      </CardContent>
      <CardFooter>
        {dirty ? <span className="mr-auto text-xs text-[#ffa931]">有未保存的修改</span> : null}
        <Button onClick={submit} disabled={bad || !dirty} loading={save.isPending}>
          保存
        </Button>
      </CardFooter>
    </Card>
  );
}
