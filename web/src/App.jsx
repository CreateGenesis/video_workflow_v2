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

const STANDALONE = [
  ["任务", "jobs"],
  ["工具", "tools"],
  ["管理", "admin"],
];

async function loadView(workId = "") {
  const query = workId ? `?work_id=${encodeURIComponent(workId)}` : "";
  const [canvasResponse, workspaceResponse, workResponse] = await Promise.all([
    fetch(`/api/view${query}`, { headers: adminHeaders() }),
    fetch("/api/workspaces", { headers: adminHeaders() }),
    fetch("/api/works", { headers: adminHeaders() }),
  ]);
  if (!canvasResponse.ok) throw new Error(await canvasResponse.text());
  const canvas = await canvasResponse.json();
  const workspaces = workspaceResponse.ok ? (await workspaceResponse.json()).items || [] : canvas.workspaces;
  const works = workResponse.ok ? (await workResponse.json()).items || [] : [];
  return { ...canvas, workspaces, works };
}

function adminHeaders() {
  const token = window.sessionStorage.getItem("cvgen_admin") || "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function App() {
  const [page, setPage] = useState("work");
  const [focus, setFocus] = useState("");
  const [view, setView] = useState({ nodes: [], edges: [], jobs: [], workspaces: [], works: [], selected: {}, settings: {} });
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
    const workId = window.sessionStorage.getItem("cvgen_work") || "";
    loadView(workId).then(setView).catch((err) => setError(String(err)));
    const timer = setInterval(() => loadView(window.sessionStorage.getItem("cvgen_work") || "").then(setView).catch(() => {}), 5000);
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
          <p className="mt-2 text-sm opacity-80">按作品查看。关系和生成由服务执行。</p>
        </div>
        <WorkspaceNav view={view} page={page} onOpen={() => setPage("work")} onRefresh={(workId) => loadView(workId || "").then(setView)} />
        <nav className="flex gap-1 overflow-x-auto px-3 pb-4 md:block">
          {STANDALONE.map(([label, value]) => (
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
        {page === "work" && <WorkSpace view={view} focus={focus} onRefresh={() => loadView(window.sessionStorage.getItem("cvgen_work") || "").then(setView)} />}
        {page === "jobs" && <Jobs view={view} onOpen={(id) => { setFocus(id); setPage("work"); }} />}
        {page === "tools" && <Tools />}
        {page === "admin" && <Admin view={view} onLogout={() => setSession("out")} />}
      </main>
    </div>
  );
}

function WorkspaceNav({ view, page, onOpen, onRefresh }) {
  const [title, setTitle] = useState("");
  const [workTitle, setWorkTitle] = useState("");
  const selectedWorkspace = view.selected?.workspace_id;
  const selectedWork = view.selected?.work_id;

  async function post(path, body) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    const workId = data.work_id || (path === "/api/works" ? data.id : "");
    if (workId) window.sessionStorage.setItem("cvgen_work", workId);
    onRefresh(workId || window.sessionStorage.getItem("cvgen_work") || "");
  }

  return (
    <div className="space-y-3 px-3 pb-4">
      <p className="px-2 text-xs uppercase tracking-[0.16em] opacity-70">工作区</p>
      {(view.workspaces || []).map((item) => (
        <div key={item.id} className="flex gap-1">
          <Button variant={item.id === selectedWorkspace ? "secondary" : "ghost"} className="flex-1 justify-start" onClick={() => post("/api/workspaces/use", { id: item.id })}>
            {item.title}
          </Button>
          <Button variant="ghost" onClick={() => { const next = window.prompt("工作区名称", item.title); if (next) post(`/api/workspaces/${item.id}/rename`, { title: next }); }}>改名</Button>
        </div>
      ))}
      <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); post("/api/workspaces", { title }); setTitle(""); }}>
        <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="新工作区" />
        <Button type="submit" variant="secondary">新建</Button>
      </form>
      <p className="px-2 text-xs uppercase tracking-[0.16em] opacity-70">作品</p>
      {(view.works || []).map((item) => (
        <Button key={item.id} variant={page === "work" && item.id === selectedWork ? "secondary" : "ghost"} className="w-full justify-start" onClick={async () => { await post("/api/works/use", { id: item.id }); onOpen(); }}>
          {item.title}
        </Button>
      ))}
      <form className="flex gap-2" onSubmit={(event) => { event.preventDefault(); post("/api/works", { title: workTitle, kind: "广告" }); setWorkTitle(""); }}>
        <Input value={workTitle} onChange={(event) => setWorkTitle(event.target.value)} placeholder="新作品" />
        <Button type="submit" variant="secondary">新建</Button>
      </form>
    </div>
  );
}

function EntityNode({ data }) {
  return (
    <div className="w-44 rounded-lg border bg-card p-2 text-xs shadow-sm">
      {data.preview ? <img src={data.preview} alt="缩略图" className="mb-2 h-16 w-full rounded object-cover" /> : null}
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium">{data.title}</span>
        <Badge status={data.status}>{data.status}</Badge>
      </div>
      <p className="mt-1 text-muted-foreground">{data.type}</p>
    </div>
  );
}

const nodeTypes = { entity: EntityNode };

function WorkSpace({ view, focus, onRefresh }) {
  const types = [...new Set(view.nodes.map((node) => node.type))];
  const [shown, setShown] = useState([]);
  useEffect(() => {
    setShown((current) => current.length ? current : types);
  }, [view.nodes]);
  const [media, setMedia] = useState(null);
  const [prompt, setPrompt] = useState(null);
  const active = new Set(view.jobs.filter((job) => job.status === "queued" || job.status === "running").map((job) => job.target_id));
  const visible = new Set(view.nodes.filter((node) => shown.includes(node.type)).map((node) => node.id));
  const nodes = useMemo(() => view.nodes.filter((node) => visible.has(node.id)).map((node, index) => ({
    id: node.id,
    type: "entity",
    selected: node.id === focus,
    position: node.position?.x !== undefined ? node.position : { x: (index % 4) * 240, y: Math.floor(index / 4) * 170 },
    data: { title: node.title, status: node.status, type: node.type, preview: node.preview_url },
  })), [view.nodes, focus, shown]);
  const edges = view.edges.filter((edge) => visible.has(edge.source_id) && visible.has(edge.target_id)).map((edge) => ({
    id: edge.id,
    source: edge.source_id,
    target: edge.target_id,
    label: edge.plain,
    className: active.has(edge.source_id) || active.has(edge.target_id) ? "edge-flow" : "",
    animated: active.has(edge.source_id) || active.has(edge.target_id),
  }));
  const previews = view.nodes.filter((node) => node.preview_url);

  async function savePositions(_event, node) {
    const positions = Object.fromEntries(nodes.map((item) => [item.id, item.id === node.id ? node.position : item.position]));
    await fetch("/api/layout", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ positions }),
    });
  }

  async function tidy() {
    await fetch("/api/layout/tidy", { method: "POST", headers: adminHeaders() });
    onRefresh();
  }

  async function openPrompt(id) {
    const data = await fetch(`/api/shots/${id}/prompt`, { headers: adminHeaders() }).then((response) => response.json());
    setPrompt({ id, versions: data.versions || [], text: data.versions?.at(-1)?.text || "" });
  }

  if (!view.selected?.work_id) return <Empty>先在侧栏选择工作区和作品。</Empty>;
  return (
    <section className="grid gap-4 xl:grid-cols-[1.4fr_0.6fr]">
      <div className="space-y-3">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">作品画布</h2>
            <p className="text-sm text-muted-foreground">可以拖动和筛选。拖动不改变关系。</p>
          </div>
          <Button type="button" variant="outline" onClick={tidy}>整理布局</Button>
        </header>
        <div className="flex flex-wrap gap-2">
          {types.map((type) => (
            <Button key={type} type="button" size="sm" variant={shown.includes(type) ? "secondary" : "outline"} onClick={() => setShown((current) => current.includes(type) ? current.filter((item) => item !== type) : [...current, type])}>
              {type}
            </Button>
          ))}
        </div>
        <div className="h-[68vh] overflow-hidden rounded-xl border bg-card">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView nodesConnectable={false} onNodeDragStop={savePositions}>
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </div>
      <div className="space-y-3">
        <h2 className="text-xl font-semibold">预览</h2>
        {previews.map((node) => (
          <Card key={node.id}>
            <button type="button" className="block w-full" onClick={() => setMedia(node)}>
              <img className="max-h-56 w-full rounded-t-xl bg-muted object-contain" src={node.preview_url} alt={node.title} />
            </button>
            <CardHeader>
              <CardTitle className="flex items-center justify-between">{node.title}<Badge status={node.status}>{node.status}</Badge></CardTitle>
              <CardDescription>{node.type} · {node.summary}</CardDescription>
            </CardHeader>
            {node.type === "Shot" && <CardContent><Button type="button" variant="outline" onClick={() => openPrompt(node.id)}>提示词</Button></CardContent>}
            {node.type === "Reference" && <CardContent><Button type="button" variant="outline" onClick={() => fetch(`/api/images/${node.id}/redraw`, { method: "POST", headers: adminHeaders() }).then(onRefresh)}>重新抽卡</Button></CardContent>}
          </Card>
        ))}
        {previews.length === 0 && <Empty>这个作品还没有可预览的文件。</Empty>}
      </div>
      {media && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-6" role="dialog" aria-label="全屏" onClick={() => setMedia(null)}>
          <div className="max-h-full max-w-5xl" onClick={(event) => event.stopPropagation()}>
            {String(media.preview_url).includes(".mp4") || media.type === "Clip" ? (
              <video className="max-h-[80vh] w-full" src={media.preview_url} controls autoPlay />
            ) : <img className="max-h-[80vh] w-full object-contain" src={media.preview_url} alt={media.title} />}
            <Button className="mt-3" type="button" onClick={() => setMedia(null)}>关闭</Button>
          </div>
        </div>
      )}
      {prompt && (
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>提示词</CardTitle><CardDescription>按时间保留。恢复会再写入一版。</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <textarea className="min-h-24 w-full rounded-md border bg-background p-3" value={prompt.text} onChange={(event) => setPrompt({ ...prompt, text: event.target.value })} />
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={() => fetch(`/api/shots/${prompt.id}/prompt`, { method: "POST", headers: { "Content-Type": "application/json", ...adminHeaders() }, body: JSON.stringify({ text: prompt.text }) }).then(() => openPrompt(prompt.id))}>保存</Button>
              {prompt.versions.map((item, index) => (
                <Button key={`${item.at}-${index}`} type="button" variant="outline" onClick={() => fetch(`/api/shots/${prompt.id}/prompt/restore`, { method: "POST", headers: { "Content-Type": "application/json", ...adminHeaders() }, body: JSON.stringify({ index }) }).then(() => openPrompt(prompt.id))}>
                  {item.at?.slice(11, 19) || index}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </section>
  );
}

function Jobs({ view, onOpen }) {
  async function retry(id) {
    await fetch(`/api/jobs/${id}/retry`, { method: "POST", headers: adminHeaders() });
  }
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">任务</h2>
      {view.jobs.map((job) => {
        const retryable = job.status === "failed" || (job.status === "unknown" && !job.detail.provider_task);
        return (
          <Card key={job.id}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">{job.kind} <Badge status={job.status}>{job.status}</Badge></CardTitle>
              <CardDescription>{job.detail.error || job.id}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {job.detail.prompt && <pre className="whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">{job.detail.prompt}</pre>}
              {job.detail.estimate_yuan ? <p className="text-sm">估算花费 {job.detail.estimate_yuan} 元，不是已核对账单。</p> : null}
              {job.detail.sheet_key_url && <img className="w-full rounded-md border" src={job.detail.sheet_key_url} alt="接触表" />}
              <div className="flex gap-2">
                {retryable && <Button type="button" onClick={() => retry(job.id)}>重试</Button>}
                {job.target_id && <Button type="button" variant="outline" onClick={() => onOpen(job.target_id)}>打开画布</Button>}
              </div>
            </CardContent>
          </Card>
        );
      })}
      {view.jobs.length === 0 && <Empty>还没有托管任务。</Empty>}
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
        <p className="text-sm text-muted-foreground">压缩包里有可执行文件和使用说明。Linux 和 macOS 运行 ./cvgen，Windows 运行 cvgen.exe。先运行 cvgen login，再由管理员批准。同时只能有一台在线。</p>
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
  const [currentPassword, setCurrentPassword] = useState("");
  const [nextPassword, setNextPassword] = useState("");
  const [recovery, setRecovery] = useState("");
  const [passwordMessage, setPasswordMessage] = useState("");

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

  async function resetLoggedOut(event) {
    event.preventDefault();
    const response = await fetch("/api/admin/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recovery, next_password: nextPassword }),
    });
    const data = await response.json();
    if (!response.ok) {
      setPasswordMessage(data.detail || "没有重设");
      return;
    }
    window.sessionStorage.setItem("cvgen_admin", data.token);
    setToken(data.token);
    setRecovery("");
    setNextPassword("");
    setPassword("");
    setPasswordMessage("");
    if (onLogin) onLogin();
  }

  async function resetLoggedIn(event) {
    event.preventDefault();
    const response = await fetch("/api/admin/password", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ password: currentPassword, next_password: nextPassword }),
    });
    const data = await response.json();
    if (!response.ok) {
      setPasswordMessage(data.detail || "没有重设");
      return;
    }
    window.sessionStorage.setItem("cvgen_admin", data.token);
    setToken(data.token);
    setCurrentPassword("");
    setNextPassword("");
    setPasswordMessage("密码已重设。当前页面仍保持登录。");
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
              <TabsTrigger value="reset">重设密码</TabsTrigger>
            </TabsList>
            <TabsContent value="reset">
              <form className="mt-4 space-y-3" onSubmit={resetLoggedOut}>
                <div className="space-y-1">
                  <Label htmlFor="recovery">恢复口令</Label>
                  <Input id="recovery" type="password" value={recovery} onChange={(event) => setRecovery(event.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="reset-next">新密码</Label>
                  <Input id="reset-next" type="password" value={nextPassword} onChange={(event) => setNextPassword(event.target.value)} />
                </div>
                <Button type="submit">重设并登录</Button>
                <p className="text-sm text-muted-foreground">恢复口令来自服务环境，只用于忘记登录密码。新密码至少 8 位。旧登录会失效。</p>
                {passwordMessage && <p className="text-sm text-muted-foreground">{passwordMessage}</p>}
              </form>
            </TabsContent>
            <TabsContent value={mode === "reset" ? "login" : mode}>
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
      <Card>
        <CardHeader>
          <CardTitle>重设密码</CardTitle>
          <CardDescription>用当前密码换成新密码。保存后这一次登录仍有效，其他旧登录失效。新密码至少 8 位。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]" onSubmit={resetLoggedIn}>
            <div className="space-y-1">
              <Label htmlFor="current-pass">当前密码</Label>
              <Input id="current-pass" type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="next-pass">新密码</Label>
              <Input id="next-pass" type="password" value={nextPassword} onChange={(event) => setNextPassword(event.target.value)} />
            </div>
            <Button className="self-end" type="submit">重设密码</Button>
          </form>
          {passwordMessage && <p className="mt-3 text-sm text-muted-foreground">{passwordMessage}</p>}
        </CardContent>
      </Card>
      <Separator />
      <p className="text-sm text-muted-foreground">ffmpeg 透传现在是{view.settings.ffmpeg_passthrough ? "打开" : "关闭"}。开关只能由已授权的 cvgen 改。</p>
      <PlatformBind />
      <ProviderSettings />
    </section>
  );
}

const PROVIDERS = [
  ["video", "生视频"],
  ["image", "生图"],
  ["music", "生音乐"],
];

function ProviderSettings() {
  const [items, setItems] = useState([]);
  const [forms, setForms] = useState({
    video: { base: "", key: "" },
    image: { base: "", key: "" },
    music: { base: "", key: "" },
  });
  const [message, setMessage] = useState("");
  const [probes, setProbes] = useState({});
  const [models, setModels] = useState({});
  const [picked, setPicked] = useState({});

  async function refresh() {
    const response = await fetch("/api/settings/providers", { headers: adminHeaders() });
    if (!response.ok) return;
    const data = await response.json();
    setItems(data.items || []);
    setForms((current) => {
      const next = { ...current };
      for (const item of data.items || []) {
        next[item.capability] = {
          ...next[item.capability],
          base: item.base || "",
          key: "",
        };
      }
      return next;
    });
  }

  useEffect(() => {
    refresh();
  }, []);

  function update(capability, field, value) {
    setForms((current) => ({ ...current, [capability]: { ...current[capability], [field]: value } }));
  }

  async function probe(capability) {
    setProbes((current) => ({ ...current, [capability]: { message: "正在检测连通…" } }));
    const response = await fetch("/api/provider/probe", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ capability }),
    });
    const data = await response.json();
    setProbes((current) => ({
      ...current,
      [capability]: response.ok ? data : { reachable: false, message: data.detail || "无法连通" },
    }));
  }

  async function loadModels(capability) {
    setMessage("正在获取上游模型…");
    const response = await fetch("/api/provider/models", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ capability }),
    });
    const data = await response.json();
    if (!response.ok) {
      setMessage(data.detail || "模型列表没有返回");
      return;
    }
    setModels((current) => ({ ...current, [capability]: data.items || [] }));
    setPicked((current) => ({ ...current, [capability]: data.items?.[0]?.id || "" }));
    setMessage(data.items?.length ? `已获取 ${data.items.length} 个模型` : "上游没有返回模型");
  }

  async function applyModel(capability) {
    const source = picked[capability];
    if (!source) {
      setMessage("先获取上游模型");
      return;
    }
    const response = await fetch("/api/provider/model", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ capability, source }),
    });
    const data = await response.json();
    setMessage(response.ok ? `已选模型 ${data.model}` : data.detail || "没有应用");
    if (response.ok) refresh();
  }

  async function save(event, capability) {
    event.preventDefault();
    const form = forms[capability];
    const response = await fetch("/api/settings/providers", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ capability, base: form.base, key: form.key }),
    });
    const data = await response.json();
    setMessage(response.ok ? `${capability} 已保存，密钥只留在服务端` : data.detail || "没有保存");
    if (response.ok) refresh();
  }

  const known = Object.fromEntries(items.map((item) => [item.capability, item]));
  return (
    <Card>
      <CardHeader>
        <CardTitle>生视频、生图、生音乐</CardTitle>
        <CardDescription>已保存的值覆盖同名环境变量。页面只显示是否已配置，密钥回显打码。留空密钥表示沿用已保存的密钥。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {PROVIDERS.map(([capability, label]) => {
          const item = known[capability] || {};
          const form = forms[capability];
          return (
            <form key={capability} className="grid gap-3 border-t border-border pt-4 first:border-0 first:pt-0" onSubmit={(event) => save(event, capability)}>
              <div className="flex items-center justify-between">
                <p className="font-medium">{label}</p>
                <Badge status={item.configured ? "在线" : "离线"}>{item.configured ? "已配置" : "未配置"}{item.key ? ` ${item.key}` : ""}</Badge>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <Label htmlFor={`${capability}-base`}>地址</Label>
                  <Input id={`${capability}-base`} value={form.base} onChange={(event) => update(capability, "base", event.target.value)} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`${capability}-key`}>访问密钥</Label>
                  <Input id={`${capability}-key`} type="password" value={form.key} onChange={(event) => update(capability, "key", event.target.value)} placeholder={item.key || "未配置"} />
                </div>
              </div>
              <Button className="w-fit" type="submit">保存{label}</Button>
              <p className="text-sm">已选模型：{item.model || "还没有选择"}</p>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" onClick={() => probe(capability)}>检测连通</Button>
              <Button type="button" variant="outline" onClick={() => loadModels(capability)}>获取上游模型</Button>
            </div>
            {probes[capability] && <p className="text-base font-medium">{probes[capability].message}</p>}
            {(models[capability] || []).length > 0 && (
              <div className="flex flex-col gap-2 sm:flex-row">
                <select className="h-9 rounded-md border bg-background px-3" value={picked[capability] || ""} onChange={(event) => setPicked((current) => ({ ...current, [capability]: event.target.value }))}>
                  {(models[capability] || []).map((model) => <option key={model.id} value={model.id}>{model.id}</option>)}
                </select>
                <Button type="button" onClick={() => applyModel(capability)}>应用</Button>
              </div>
            )}
            </form>
          );
        })}
        {message && <p className="text-sm text-muted-foreground">{message}</p>}
      </CardContent>
    </Card>
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
