import { Suspense, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes,
  ChevronsLeft,
  ChevronsRight,
  ChevronsUpDown,
  Clapperboard,
  LayoutDashboard,
  ListOrdered,
  LogOut,
  Menu,
  Settings,
  Telescope,
  UserRound,
  Workflow,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Skeleton,
  Tooltip,
} from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { ROLE } from "@/lib/labels";
import { useLiveUpdates, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "工作台", icon: LayoutDashboard, end: true },
  { group: "agent 探索" },
  { to: "/explore", label: "探索审计", icon: Telescope, perm: "works:read", hint: "看 agent 在做什么、留意见" },
  { to: "/library", label: "素材库", icon: Boxes, perm: "assets:read", hint: "定型的风格、角色、参考图、模板" },
  { group: "生产" },
  { to: "/workflows", label: "工作流", icon: Workflow, perm: "workflows:read", hint: "agent 定型的出片流程，审过后发布" },
  { to: "/runs", label: "运行", icon: Clapperboard, perm: "runs:read", hint: "用已发布的工作流出片" },
  { to: "/queue", label: "队列", icon: ListOrdered, perm: "queue:read", badge: "attention", hint: "排队、GPU 占用、等人处理的任务" },
  { group: "" },
  { to: "/settings", label: "设置", icon: Settings },
];

function useAttentionCount(enabled) {
  const query = useQuery({
    queryKey: ["tasks", "attention-count"],
    queryFn: () => api.get("/api/tasks?status=needs_attention,waiting&limit=200"),
    enabled,
    staleTime: 15_000,
  });
  return query.data?.items?.length || 0;
}

function NavItems({ collapsed, onNavigate, attention }) {
  const { can } = useSession();
  return (
    <nav className="flex flex-col gap-0.5">
      {NAV.filter((item) => !item.perm || can(item.perm)).map((item, index) => {
        if ("group" in item) {
          if (collapsed) return <div key={`g${index}`} className="mx-2 my-1.5 border-t border-[#303030]" />;
          return item.group ? (
            <div key={`g${index}`} className="px-2.5 pt-3 pb-1 text-[11px] font-medium text-[#777]">
              {item.group}
            </div>
          ) : (
            <div key={`g${index}`} className="mx-2 my-2 border-t border-[#303030]" />
          );
        }
        const Icon = item.icon;
        const count = item.badge === "attention" ? attention : 0;
        const link = (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            title={collapsed ? undefined : item.hint}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "relative flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm text-[#ccc] transition-colors hover:bg-[#303030] hover:text-white",
                isActive && "bg-accent font-medium text-accent-foreground hover:bg-accent hover:text-accent-foreground",
                collapsed && "justify-center px-0",
              )
            }
          >
            <Icon className="size-4 shrink-0" />
            {collapsed ? null : <span className="flex-1 truncate">{item.label}</span>}
            {count ? (
              <span
                className={cn(
                  "tnum rounded-full bg-[#3a2218] px-1.5 text-[11px] font-semibold leading-5 text-[#ffa931] ring-1 ring-inset ring-[#6a3a22]",
                  collapsed && "absolute -right-0.5 -top-0.5 px-1 text-[10px] leading-4",
                )}
              >
                {count}
              </span>
            ) : null}
          </NavLink>
        );
        return collapsed ? (
          <Tooltip key={item.to} content={item.label} side="right">
            {link}
          </Tooltip>
        ) : (
          link
        );
      })}
    </nav>
  );
}

function WorkspaceSwitcher({ compact }) {
  const { workspaces, workspace, setWorkspace, workspacesLoading } = useSession();
  const client = useQueryClient();
  if (workspacesLoading) return <Skeleton className="h-8 w-36" />;
  if (!workspace) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className={cn(
            "flex h-8 max-w-56 items-center gap-2 rounded-md border bg-card px-2.5 text-[13px] shadow-xs hover:bg-muted",
            compact && "max-w-40",
          )}
          aria-label="切换工作区"
        >
          <span className="size-2 shrink-0 rounded-full bg-primary/70" />
          <span className="truncate font-medium">{workspace.name}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>工作区</DropdownMenuLabel>
        {workspaces.map((item) => (
          <DropdownMenuItem
            key={item.id}
            onSelect={() => {
              setWorkspace(item.id);
              client.invalidateQueries();
            }}
            className={cn(item.id === workspace.id && "font-medium text-primary")}
          >
            <span className={cn("size-2 rounded-full", item.id === workspace.id ? "bg-primary" : "bg-[#4e4e4e]")} />
            {item.name}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const { me } = useSession();
  const navigate = useNavigate();
  const client = useQueryClient();
  const logout = useMutation({
    mutationFn: () => api.post("/api/auth/logout"),
    onSuccess: () => {
      client.clear();
      navigate("/login", { replace: true });
    },
    onError: (error) => toast.error("退出失败", error.message),
  });
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex h-8 items-center gap-2 rounded-md px-1.5 hover:bg-muted" aria-label="账号菜单">
          <span className="flex size-7 items-center justify-center rounded-full bg-[#123044] text-xs font-semibold text-[#64b5f6]">
            {(me.name || "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="hidden text-left leading-tight sm:block">
            <span className="block text-[13px] font-medium">{me.name}</span>
            <span className="block text-[11px] text-muted-foreground">{ROLE[me.role] || me.role}</span>
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>
          {me.name} · {ROLE[me.role] || me.role}
        </DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => navigate("/settings?tab=account")}>
          <UserRound />
          我的账号
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => logout.mutate()}>
          <LogOut />
          退出登录
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Brand({ collapsed }) {
  return (
    <div className={cn("flex items-center gap-2", collapsed && "justify-center")}>
      <span className="flex size-7 items-center justify-center rounded-md bg-primary text-[13px] font-bold text-white">cv</span>
      {collapsed ? null : (
        <span className="leading-tight">
          <span className="block text-sm font-semibold">cvgen</span>
          <span className="block text-[11px] text-muted-foreground">视频生产控制台</span>
        </span>
      )}
    </div>
  );
}

function PageFallback() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-7 w-48" />
      <Skeleton className="h-4 w-80" />
      <div className="grid gap-3 sm:grid-cols-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

export function AppLayout() {
  const { can } = useSession();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("cvgen.nav") === "collapsed");
  const [menuOpen, setMenuOpen] = useState(false);
  const connected = useLiveUpdates(true);
  const attention = useAttentionCount(can("queue:read"));
  const location = useLocation();

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem("cvgen.nav", next ? "collapsed" : "open");
  };

  return (
    <div className="min-h-dvh md:flex">
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-[#4e4e4e] bg-[#171718] md:flex",
          collapsed ? "w-[60px]" : "w-[216px]",
        )}
      >
        <div className={cn("flex h-14 items-center border-b px-4", collapsed && "px-2")}>
          <Brand collapsed={collapsed} />
        </div>
        <div className={cn("flex-1 overflow-y-auto p-3", collapsed && "px-2")}>
          <NavItems collapsed={collapsed} attention={attention} />
        </div>
        <div className={cn("border-t p-3", collapsed && "px-2")}>
          <div className={cn("mb-2 flex items-center gap-1.5 px-1 text-[11px] text-muted-foreground", collapsed && "justify-center")}>
            <span className={cn("size-1.5 rounded-full", connected ? "bg-[#81c784]" : "bg-[#4e4e4e]")} />
            {collapsed ? null : connected ? "实时更新已连接" : "实时更新未连接"}
          </div>
          <Button variant="ghost" size="sm" className={cn("w-full justify-start text-muted-foreground", collapsed && "justify-center px-0")} onClick={toggle}>
            {collapsed ? <ChevronsRight /> : <ChevronsLeft />}
            {collapsed ? null : "收起导航"}
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-[#4e4e4e] bg-[#171718] px-3 sm:px-6">
          <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={() => setMenuOpen(true)} aria-label="打开菜单">
            <Menu />
          </Button>
          <div className="md:hidden">
            <Brand collapsed />
          </div>
          <WorkspaceSwitcher compact />
          <div className="flex-1" />
          <UserMenu />
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-3 py-5 sm:px-6 sm:py-6">
          <Suspense fallback={<PageFallback />} key={location.pathname.split("/")[1]}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen} side="left" title={<Brand />}>
        <div className="p-3">
          <NavItems attention={attention} onNavigate={() => setMenuOpen(false)} />
          <div className="mt-4 flex items-center gap-1.5 px-2 text-[11px] text-muted-foreground">
            <span className={cn("size-1.5 rounded-full", connected ? "bg-[#81c784]" : "bg-[#4e4e4e]")} />
            {connected ? "实时更新已连接" : "实时更新未连接"}
          </div>
        </div>
      </Sheet>
    </div>
  );
}
