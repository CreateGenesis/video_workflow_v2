import { StrictMode, Suspense, lazy, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from "react-router";
import { MutationCache, QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout";
import { ConfirmProvider } from "@/components/common";
import { Skeleton, TooltipProvider } from "@/components/ui/misc";
import { Toaster, toast } from "@/components/ui/toast";
import { onUnauthorized, uiFlags } from "@/lib/api";
import { CONSOLE_ROUTES } from "@/lib/routes";
import { SessionProvider, useAuthStatus } from "@/lib/session";
import "./styles.css";

const PAGES = {
  login: lazy(() => import("@/pages/login")),
  approve: lazy(() => import("@/pages/approve")),
  dashboard: lazy(() => import("@/pages/dashboard")),
  explore: lazy(() => import("@/pages/explore")),
  work: lazy(() => import("@/pages/work")),
  workflows: lazy(() => import("@/pages/workflows")),
  workflow: lazy(() => import("@/pages/workflow")),
  "workflow-version": lazy(() => import("@/pages/workflow-version")),
  runs: lazy(() => import("@/pages/runs")),
  "run-new": lazy(() => import("@/pages/run-new")),
  run: lazy(() => import("@/pages/run")),
  queue: lazy(() => import("@/pages/queue")),
  library: lazy(() => import("@/pages/library")),
  settings: lazy(() => import("@/pages/settings")),
  "not-found": lazy(() => import("@/pages/not-found")),
};

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
      refetchOnWindowFocus: true,
      staleTime: 5_000,
      retry: (count, error) => (error?.status === 0 || error?.status >= 500) && count < 2,
    },
  },
});

function FullScreenLoading() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <div className="w-64 space-y-3">
        <Skeleton className="mx-auto size-10 rounded-lg" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    </div>
  );
}

function UnauthorizedRedirect() {
  const navigate = useNavigate();
  const client = useQueryClient();
  const location = useLocation();
  useEffect(() => {
    onUnauthorized(() => {
      if (window.location.pathname.startsWith("/login")) return;
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
  if (status.isLoading) return <FullScreenLoading />;
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
  const Page = PAGES[name];
  return (
    <Suspense fallback={<FullScreenLoading />}>
      <Page />
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
