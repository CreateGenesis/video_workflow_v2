import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppLayout } from "@/components/layout";
import { ConfirmProvider } from "@/components/common";
import { TooltipProvider } from "@/components/ui/misc";
import { Toaster, toast } from "@/components/ui/toast";
import { uiFlags } from "@/lib/api";
import { CONSOLE_ROUTES } from "@/lib/routes";
import "./styles.css";

const LOADERS = {
  products: () => import("@/pages/products"),
  settings: () => import("@/pages/settings"),
  comic: () => import("@/pages/comic"),
  "not-found": () => import("@/pages/not-found"),
};
const PAGES = Object.fromEntries(Object.entries(LOADERS).map(([name, load]) => [name, lazy(load)]));

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
    </Routes>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <BrowserRouter>
          <ConfirmProvider>
            <App />
          </ConfirmProvider>
        </BrowserRouter>
        <Toaster />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
