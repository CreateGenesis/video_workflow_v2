import { StrictMode, Suspense, lazy, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router";
import { MutationCache, QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout";
import { ConfirmProvider } from "@/components/common";
import { TooltipProvider } from "@/components/ui/misc";
import { Toaster, toast } from "@/components/ui/toast";
import { onUnauthorized, uiFlags } from "@/lib/api";
import { CONSOLE_ROUTES } from "@/lib/routes";
import { SessionProvider, useAuthStatus, writeAuthHint } from "@/lib/session";
import "./styles.css";

const LOADERS = {
  login: () => import("@/pages/login"),
  approve: () => import("@/pages/approve"),
  dashboard: () => import("@/pages/dashboard"),
  explore: () => import("@/pages/explore"),
  work: () => import("@/pages/work"),
  workflows: () => import("@/pages/workflows"),
  workflow: () => import("@/pages/workflow"),
  "workflow-version": () => import("@/pages/workflow-version"),
  runs: () => import("@/pages/runs"),
  "run-new": () => import("@/pages/run-new"),
  run: () => import("@/pages/run"),
  queue: () => import("@/pages/queue"),
  library: () => import("@/pages/library"),
  products: () => import("@/pages/products"),
  settings: () => import("@/pages/settings"),
  "not-found": () => import("@/pages/not-found"),
};
const PAGES = Object.fromEntries(Object.entries(LOADERS).map(([name, load]) => [name, lazy(load)]));

// Start every console chunk while auth is in flight, so opening a page does not flash a second loader.
function warmPages() {
  for (const load of Object.values(LOADERS)) load();
}

const queryClient = new QueryClient({
  // Failed actions show the server's detail as a toast, unless the form shows it inline (meta.inline)
  // or a confirmation dialog is already showing it.
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (mutation.meta?.inline || uiFlags.confirmActive) return;
      toast.error(mutation.meta?.errorTitle || "操作失败", error?.message);
    },
  }),
  defaultOptions: {
    queries: {
      // Focus and live events must not blank a page that already has data.
      refetchOnWindowFocus: false,
      staleTime: 15_000,
      placeholderData: (previous) => previous,
      retry: (count, error) => (error?.status === 0 || error?.status >= 500) && count < 2,
    },
  },
});

function FullScreenLoading() {
  return <div className="min-h-dvh bg-[#202020]" aria-busy="true" />;
}

function UnauthorizedRedirect() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const location = useLocation();
  useEffect(() => {
    onUnauthorized(() => {
      if (window.location.pathname.startsWith("/login")) return;
      writeAuthHint(null);
      client.setQueryData(["auth-status"], (old) => (old ? { ...old, signed_in: false, me: null } : old));
      const next = window.location.pathname + window.location.search;
      navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
    });
  }, [navigate, client, location.pathname]);
  return null;
}

function RequireSession() {
  const status = useAuthStatus();
  const location = useLocation();
  // placeholderData keeps isLoading false after a reload, so this only covers a cold first visit.
  useEffect(() => {
    if (status.data?.signed_in) warmPages();
  }, [status.data?.signed_in]);
  if (status.isLoading && !status.data) return <FullScreenLoading />;
  if (status.isError) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-6 text-center">
        <div>
          <p className="font-medium text-[#ff6e6e]">连不上服务器</p>
          <p className="mt-1 text-sm text-[#ff9c9c]">{status.error.message}</p>
          <button className="mt-3 text-sm text-primary underline" onClick={() => status.refetch()}>
            重试
          </button>
        </div>
      </div>
    );
  }
  if (!status.data?.signed_in) {
    const next = location.pathname + location.search;
    return <Navigate to={`/login${next && next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`} replace />;
  }
  return (
    <SessionProvider me={status.data.me}>
      <Outlet />
    </SessionProvider>
  );
}

function LazyPage({ name }) {
  const View = PAGES[name];
  return (
    <Suspense fallback={null}>
      <View />
    </Suspense>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LazyPage name="login" />} />
      <Route element={<RequireSession />}>
        <Route path="/approve/:code" element={<LazyPage name="approve" />} />
        <Route path="/approve" element={<LazyPage name="approve" />} />
        <Route element={<AppLayout />}>
          {CONSOLE_ROUTES.map((route) => (
            <Route
              key={route.path}
              index={route.index}
              path={route.index ? undefined : route.path.slice(1)}
              element={<LazyPage name={route.page} />}
            />
          ))}
          <Route path="*" element={<LazyPage name="not-found" />} />
        </Route>
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <BrowserRouter>
          <ConfirmProvider>
            <UnauthorizedRedirect />
            <App />
          </ConfirmProvider>
        </BrowserRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
