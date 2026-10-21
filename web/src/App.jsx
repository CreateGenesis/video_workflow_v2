import React, { useEffect, useMemo, useState } from "react";
import { Background, Controls, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Download, LogOut, Monitor, Shield } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const PAGES = [
  ["作品", "works"],
  ["画布", "canvas"],
  ["预览", "preview"],
  ["任务", "jobs"],
  ["技能", "skills"],
  ["工具", "tools"],
  ["管理", "admin"],
];

async function loadView() {
  const response = await fetch("/api/view", { headers: adminHeaders() });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function adminHeaders() {
  const token = window.sessionStorage.getItem("cvgen_admin") || "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function App() {
  const [page, setPage] = useState("works");
  const [view, setView] = useState({ nodes: [], edges: [], jobs: [], activity: [], settings: {} });
  const [error, setError] = useState("");
  const [session, setSession] = useState("checking");
  const [adminReady, setAdminReady] = useState(false);
  const online = view.settings?.cvgen;

  useEffect(() => {
    const token = window.sessionStorage.getItem("cvgen_admin") || "";
    if (!token) {
      fetch("/api/auth/status")
        .then((response) => response.json())
        .then((data) => setAdminReady(Boolean(data.admin_ready)))
        .catch(() => {})
        .finally(() => setSession("out"));
      return undefined;
    }
    let stop = false;
    fetch("/api/admin/session", { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => {
        if (stop) return;
        if (!response.ok) {
          window.sessionStorage.removeItem("cvgen_admin");
          setAdminReady(true);
          setSession("out");
          return;
        }
        setSession("in");
      })
      .catch(() => {
        if (!stop) setSession("out");
      });
    return () => {
      stop = true;
    };
  }, []);

  useEffect(() => {
    if (session !== "in") return undefined;
    loadView().then(setView).catch((err) => setError(String(err)));
    const timer = setInterval(() => loadView().then(setView).catch(() => {}), 5000);
    return () => clearInterval(timer);
  }, [session]);

  if (session !== "in") {
    return (
      <main className="grid min-h-screen place-items-center bg-background p-6">
        <div className="w-full max-w-md space-y-4">
          <div>
            <p className="text-xs tracking-[0.2em] uppercase text-muted-foreground">cvgen</p>
            <h1 className="mt-1 text-2xl font-semibold">请先登录</h1>
            <p className="mt-2 text-sm text-muted-foreground">未登录不能查看作品、画布、预览和任务。</p>
          </div>
          {session === "checking" ? <p className="text-sm text-muted-foreground">正在确认登录状态。</p> : (
            <Admin
              view={{ settings: { admin_ready: adminReady } }}
              onLogin={() => {
                setError("");
                setSession("in");
              }}
            />
          )}
        </div>
      </main>
    );
  }

  return (
    <div className="grid min-h-screen md:grid-cols-[240px_1fr]">
      <aside className="border-b bg-primary text-primary-foreground md:border-b-0 md:border-r">
        <div className="px-5 py-6">
          <p className="text-xs tracking-[0.2em] uppercase opacity-70">观察</p>
          <h1 className="mt-1 text-2xl font-semibold">cvgen</h1>
          <p className="mt-2 text-sm opacity-80">只读观察。生成和剪辑由服务执行。</p>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-4 md:block">
          {PAGES.map(([label, value]) => (
            <Button
              key={value}
              variant={page === value ? "secondary" : "ghost"}
              className={`justify-start ${page === value ? "" : "text-primary-foreground hover:bg-white/10 hover:text-primary-foreground"}`}
              onClick={() => setPage(value)}
            >
              {label}
            </Button>
          ))}
        </nav>
        <div className="hidden px-5 pb-6 md:block">
          <Badge status={online ? "在线" : "离线"}>{online ? `在线 ${online.code}` : "没有在线 cvgen"}</Badge>
        </div>
      </aside>
      <main className="p-5 md:p-8">
        {error && <p className="mb-4 text-sm text-red-700">{error}</p>}
        {page === "works" && <Works view={view} />}
        {page === "canvas" && <Canvas view={view} />}
        {page === "preview" && <Preview view={view} />}
        {page === "jobs" && <Jobs view={view} />}
        {page === "skills" && <Skills />}
        {page === "tools" && <Tools />}
        {page === "admin" && <Admin view={view} onLogout={() => setSession("out")} />}
      </main>
    </div>
  );
}

function Works({ view }) {
  const shots = view.nodes.filter((node) => node.type === "Shot");
  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold">作品里的镜头</h2>
        <p className="text-sm text-muted-foreground">agent 用 cvgen 建好后会出现在这里。</p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {shots.map((shot) => (
          <Card key={shot.id}>
            {shot.preview_url && <img className="h-40 w-full rounded-t-xl object-cover" src={shot.preview_url} alt="" />}
            <CardHeader>
              <CardTitle>{shot.title}</CardTitle>
              <CardDescription>{shot.summary}</CardDescription>
            </CardHeader>
            <CardContent>
              <Badge status={shot.status}>{shot.status}</Badge>
              {shot.status === "失败" && <p className="mt-3 text-sm text-muted-foreground">服务已执行，片子没有入库。原因在任务页。</p>}
            </CardContent>
          </Card>
        ))}
      </div>
      {shots.length === 0 && <Empty>还没有镜头。</Empty>}
    </section>
  );
}

function Canvas({ view }) {
  const nodes = useMemo(() => view.nodes.map((node, index) => ({
    id: node.id,
    position: { x: (index % 4) * 240, y: Math.floor(index / 4) * 150 },
    data: { label: `${node.title}\n${node.status}` },
  })), [view.nodes]);
  const edges = view.edges.map((edge) => ({
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    label: edge.plain,
  }));
  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold">本体画布</h2>
        <p className="text-sm text-muted-foreground">点一条边，看它在说什么。这里不能改关系。</p>
      </header>
      <div className="h-[70vh] overflow-hidden rounded-xl border bg-card">
        <ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} nodesConnectable={false} elementsSelectable>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <ul className="space-y-1 text-sm text-muted-foreground">
        {view.edges.map((edge) => <li key={edge.id}>{edge.plain}</li>)}
      </ul>
    </section>
  );
}

function Preview({ view }) {
  const media = view.nodes.filter((node) => node.preview_url);
  const latest = view.activity[0];
  return (
    <section className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">画面</h2>
        {media.map((node) => (
          <Card key={node.id}>
            <img className="max-h-80 w-full rounded-t-xl object-contain bg-muted" src={node.preview_url} alt={node.title} />
            <CardHeader>
              <CardTitle>{node.title}</CardTitle>
              <CardDescription>{node.summary}</CardDescription>
            </CardHeader>
          </Card>
        ))}
        {media.length === 0 && <Empty>还没有可预览的文件。</Empty>}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>agent 最近一次看到的返回</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="whitespace-pre-wrap font-mono text-xs">{latest ? JSON.stringify(latest, null, 2) : "还没有操作。"}</pre>
        </CardContent>
      </Card>
    </section>
  );
}

function Jobs({ view }) {
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">任务和花费</h2>
      {view.jobs.map((job) => (
        <Card key={job.id}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">{job.kind} <Badge>{job.status}</Badge></CardTitle>
            <CardDescription>{job.detail.error || job.detail.draft || job.id}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {job.detail.estimate_yuan ? <p className="text-sm">估算花费 {job.detail.estimate_yuan} 元，不是已核对账单。</p> : null}
            {job.detail.sheet_key_url && <img className="w-full rounded-md border" src={job.detail.sheet_key_url} alt="接触表" />}
          </CardContent>
        </Card>
      ))}
      {view.jobs.length === 0 && <Empty>还没有托管任务。</Empty>}
    </section>
  );
}

function Skills() {
  const [names, setNames] = useState([]);
  const [text, setText] = useState("点一个技能，看 agent 读到的同一份正文。");
  useEffect(() => {
    fetch("/api/skills", { headers: adminHeaders() }).then((response) => response.json()).then((data) => setNames(data.items || []));
  }, []);
  async function open(name) {
    const data = await fetch(`/api/skills/${name}`, { headers: adminHeaders() }).then((response) => response.json());
    setText(data.text || "");
  }
  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold">技能</h2>
        <p className="text-sm text-muted-foreground">这些正文只写 cvgen 操作。提交、轮询和入库由服务完成。</p>
      </header>
      <div className="flex flex-wrap gap-2">
        {names.map((name) => (
          <Button key={name} variant="outline" size="sm" type="button" onClick={() => open(name)}>{name}</Button>
        ))}
      </div>
      <Card>
        <CardContent className="pt-5">
          <pre className="whitespace-pre-wrap font-mono text-xs">{text}</pre>
        </CardContent>
      </Card>
    </section>
  );
}

function Tools() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    fetch("/api/tools", { headers: adminHeaders() }).then((response) => response.json()).then((data) => setItems(data.items || []));
  }, []);
  const labels = { linux: "Linux", macos: "macOS", windows: "Windows" };
  return (
    <section className="space-y-4">
      <header>
        <h2 className="text-xl font-semibold">下载 cvgen</h2>
        <p className="text-sm text-muted-foreground">下载的是可执行文件。Linux 和 macOS 解压后运行 ./cvgen，Windows 运行 cvgen.exe。先运行 cvgen login，再由管理员批准。同时只能有一台在线。</p>
      </header>
      <div className="grid gap-4 md:grid-cols-3">
        {items.map((item) => (
          <Card key={item.platform}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Download className="size-4" />{labels[item.platform]}</CardTitle>
              <CardDescription>{item.filename}</CardDescription>
            </CardHeader>
            <CardContent>
              {item.ready ? (
                <Button type="button" onClick={() => downloadTool(item)}>下载 {Math.ceil(item.bytes / 1024)} KB</Button>
              ) : <Badge>尚未构建</Badge>}
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  );
}

async function downloadTool(item) {
  const response = await fetch(item.url, { headers: adminHeaders() });
  if (!response.ok) return;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = item.filename;
  link.click();
  URL.revokeObjectURL(url);
}

function Admin({ view, onLogin, onLogout }) {
  const [token, setToken] = useState(() => window.sessionStorage.getItem("cvgen_admin") || "");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [mode, setMode] = useState(view.settings?.admin_ready ? "login" : "setup");
  const [devices, setDevices] = useState([]);
  const [code, setCode] = useState("");

  useEffect(() => {
    if (view.settings?.admin_ready) setMode("login");
  }, [view.settings?.admin_ready]);

  async function refresh(nextToken = token) {
    if (!nextToken) return;
    const response = await fetch("/api/admin/cvgen", { headers: { Authorization: `Bearer ${nextToken}` } });
    if (response.status === 401) {
      window.sessionStorage.removeItem("cvgen_admin");
      setToken("");
      return;
    }
    const data = await response.json();
    setDevices(data.items || []);
  }

  useEffect(() => {
    refresh();
  }, [token]);

  async function submit(event) {
    event.preventDefault();
    const path = mode === "setup" ? "/api/admin/setup" : "/api/admin/login";
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (!response.ok) {
      setMessage(data.detail || "没有登录");
      return;
    }
    window.sessionStorage.setItem("cvgen_admin", data.token);
    setToken(data.token);
    setPassword("");
    setMessage("");
    if (onLogin) onLogin();
  }

  async function approve(event) {
    event.preventDefault();
    const response = await fetch(`/api/device/${code}/approve`, { method: "POST", headers: adminHeaders() });
    const data = await response.json();
    setMessage(response.ok ? "已批准，这一台成为唯一在线 cvgen" : data.detail);
    if (response.ok) setCode("");
    refresh();
  }

  async function revoke(item) {
    const response = await fetch(`/api/admin/cvgen/${item}/revoke`, { method: "POST", headers: adminHeaders() });
    const data = await response.json();
    setMessage(response.ok ? "已下线" : data.detail);
    refresh();
  }

  function logout() {
    fetch("/api/admin/logout", { method: "POST", headers: adminHeaders() });
    window.sessionStorage.removeItem("cvgen_admin");
    setToken("");
    if (onLogout) onLogout();
  }

  if (!token) {
    return (
      <Card className="max-w-md">
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Shield className="size-4" />管理员</CardTitle>
          <CardDescription>{mode === "setup" ? "第一次使用先设置账号和至少 8 位密码。" : "登录后才能批准 cvgen。"}</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={mode} onValueChange={setMode}>
            <TabsList>
              <TabsTrigger value="login">登录</TabsTrigger>
              <TabsTrigger value="setup">初次设置</TabsTrigger>
            </TabsList>
            <TabsContent value={mode}>
              <form className="mt-4 space-y-3" onSubmit={submit}>
                <div className="space-y-1">
                  <Label htmlFor="admin-name">账号</Label>
                  <Input id="admin-name" value={username} onChange={(event) => setUsername(event.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="admin-pass">密码</Label>
                  <Input id="admin-pass" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
                </div>
                <Button type="submit">{mode === "setup" ? "设置并登录" : "登录"}</Button>
                {message && <p className="text-sm text-muted-foreground">{message}</p>}
              </form>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">在线 cvgen</h2>
          <p className="text-sm text-muted-foreground">同时只能有一台在线。批准第二台之前，先把当前这一台下线。</p>
        </div>
        <Button variant="outline" onClick={logout}><LogOut className="size-4" />退出</Button>
      </header>
      <Card>
        <CardHeader>
          <CardTitle>批准设备码</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={approve}>
            <Input value={code} onChange={(event) => setCode(event.target.value)} placeholder="设备码" />
            <Button type="submit">批准这台 cvgen</Button>
          </form>
          {message && <p className="mt-3 text-sm text-muted-foreground">{message}</p>}
        </CardContent>
      </Card>
      <div className="grid gap-3">
        {devices.map((item) => (
          <Card key={item.code}>
            <CardContent className="flex items-center justify-between gap-3 pt-5">
              <div>
                <p className="flex items-center gap-2 font-medium"><Monitor className="size-4" />{item.code}</p>
                <p className="text-xs text-muted-foreground">{item.seen_at || "还没有心跳"}</p>
              </div>
              <div className="flex items-center gap-2">
                <Badge status={item.online ? "在线" : "离线"}>{item.online ? "在线" : item.status}</Badge>
                {item.status === "approved" && <Button variant="outline" size="sm" onClick={() => revoke(item.code)}>下线</Button>}
              </div>
            </CardContent>
          </Card>
        ))}
        {devices.length === 0 && <Empty>还没有申请授权的 cvgen。</Empty>}
      </div>
      <Separator />
      <p className="text-sm text-muted-foreground">ffmpeg 透传现在是{view.settings.ffmpeg_passthrough ? "打开" : "关闭"}。开关只能由已授权的 cvgen 改。</p>
      <PlatformBind />
    </section>
  );
}

function PlatformBind() {
  const [name, setName] = useState("bilibili");
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState("");
  async function save(event) {
    event.preventDefault();
    const response = await fetch("/api/settings/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ name, note }),
    });
    const data = await response.json();
    setSaved(response.ok && data.saved ? `${data.name} 已记录在服务端` : data.detail || "没有保存");
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle>平台绑定</CardTitle>
        <CardDescription>外部账号只在这页记录说明。学习任务仍由服务下载并入库。</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]" onSubmit={save}>
          <div className="space-y-1">
            <Label htmlFor="platform">平台</Label>
            <Input id="platform" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="note">说明</Label>
            <Input id="note" value={note} onChange={(event) => setNote(event.target.value)} />
          </div>
          <Button className="self-end" type="submit">保存绑定说明</Button>
        </form>
        {saved && <p className="mt-3 text-sm text-muted-foreground">{saved}</p>}
      </CardContent>
    </Card>
  );
}

function Empty({ children }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}
