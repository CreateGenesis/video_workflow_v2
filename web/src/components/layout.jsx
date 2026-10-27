import { useState } from "react";
import { NavLink, Outlet } from "react-router";
import { Clapperboard, Menu, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/products", label: "产物", icon: Clapperboard, hint: "按提示词搜索生成结果" },
  { to: "/comic", label: "漫剧缺项", icon: Clapperboard, hint: "停在哪一闸门、缺哪一项" },
  { to: "/settings", label: "设置", icon: Settings, hint: "账号验证和 MCP 验证" },
];

function NavItems({ onNavigate }) {
  return (
    <nav className="flex flex-col gap-0.5">
      {NAV.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            title={item.hint}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm text-[#ccc] hover:bg-[#303030] hover:text-white",
                isActive && "bg-accent font-medium text-accent-foreground",
              )
            }
          >
            <Icon className="size-4 shrink-0" />
            <span className="flex-1 truncate">{item.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}

export function AppLayout() {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <div className="min-h-dvh md:flex">
      <aside className="sticky top-0 hidden h-dvh w-[216px] shrink-0 flex-col border-r border-[#4e4e4e] bg-[#171718] md:flex">
        <div className="flex h-14 items-center border-b px-4 text-sm font-semibold">cvgen 平台</div>
        <div className="flex-1 overflow-y-auto p-3">
          <NavItems />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-[#4e4e4e] bg-[#171718] px-3 sm:px-6">
          <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={() => setMenuOpen(true)} aria-label="打开菜单">
            <Menu />
          </Button>
          <span className="text-sm font-semibold md:hidden">cvgen 平台</span>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-3 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
      <Sheet open={menuOpen} onOpenChange={setMenuOpen} side="left" title="cvgen 平台">
        <div className="p-3">
          <NavItems onNavigate={() => setMenuOpen(false)} />
        </div>
      </Sheet>
    </div>
  );
}
