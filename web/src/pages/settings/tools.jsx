import { useQuery } from "@tanstack/react-query";
import { Apple, Download, Monitor, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyButton, QueryView, SkeletonCards } from "@/components/common";
import { api } from "@/lib/api";
import { bytes } from "@/lib/format";

const PLATFORMS = {
  linux: { label: "Linux x64", icon: Terminal },
  macos: { label: "macOS", icon: Apple },
  windows: { label: "Windows x64", icon: Monitor },
};

export default function ToolsTab() {
  const tools = useQuery({ queryKey: ["tools"], queryFn: () => api.get("/api/tools") });
  const base = window.location.origin;
  return (
    <div className="space-y-5">
      <QueryView query={tools} skeleton={<SkeletonCards count={3} />}>
        {(data) => (
          <div className="grid gap-3 sm:grid-cols-3">
            {data.items.map((item) => {
              const meta = PLATFORMS[item.platform] || { label: item.platform, icon: Download };
              const Icon = meta.icon;
              return (
                <Card key={item.platform} className="p-4">
                  <div className="flex items-center gap-2.5">
                    <span className="flex size-9 items-center justify-center rounded-lg bg-muted">
                      <Icon className="size-4.5" />
                    </span>
                    <div>
                      <p className="text-sm font-semibold">cvgen · {meta.label}</p>
                      <p className="text-xs text-muted-foreground">{item.ready ? `${data.version ? `版本 ${data.version} · ` : ""}${bytes(item.bytes)}` : "还没有构建"}</p>
                    </div>
                  </div>
                  {item.ready ? (
                    <Button asChild className="mt-3 w-full" variant="outline">
                      <a href={item.url} download={item.filename}>
                        <Download />
                        下载 {item.filename}
                      </a>
                    </Button>
                  ) : (
                    <Button className="mt-3 w-full" variant="outline" disabled>
                      暂不可下载
                    </Button>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </QueryView>
      <Card className="max-w-3xl">
        <CardHeader>
          <CardTitle>接入步骤</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="list-inside list-decimal space-y-3 text-[13px] text-[#ddd]">
            <li>下载对应平台的压缩包并解压，把 cvgen 放进 PATH。</li>
            <li>
              在终端登录这台服务器：
              <div className="mt-1.5 flex items-center gap-2">
                <code className="flex-1 overflow-x-auto rounded-md border bg-[#222] px-3 py-2 text-xs">cvgen login --base {base}</code>
                <CopyButton value={`cvgen login --base ${base}`} />
              </div>
            </li>
            <li>终端会显示一个 8 位设备码和批准链接。用已登录的浏览器打开链接，核对设备码后点「批准」。</li>
            <li>回到终端，cvgen 会自动拿到凭证。之后 agent 的所有操作都以你的名义记录，可在「设备」里随时吊销。</li>
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}
