import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

const SessionContext = createContext(null);
const WORKSPACE_KEY = "cvgen.workspace";
const AUTH_KEY = "cvgen.auth";

/** Last confirmed session, so a reload paints the console instead of a full-screen flash. */
export function readAuthHint() {
  try {
    const raw = sessionStorage.getItem(AUTH_KEY);
    if (!raw) return undefined;
    const hint = JSON.parse(raw);
    if (!hint?.signed_in || !hint.me) return undefined;
    return hint;
  } catch {
    return undefined;
  }
}

export function writeAuthHint(data) {
  try {
    if (data?.signed_in && data.me) sessionStorage.setItem(AUTH_KEY, JSON.stringify({ signed_in: true, me: data.me }));
    else sessionStorage.removeItem(AUTH_KEY);
  } catch {
    /* private mode can reject storage; the page still loads, just without the hint */
  }
}

export function useAuthStatus() {
  const query = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => api.get("/api/auth/status", { quiet401: true }),
    staleTime: 60_000,
    placeholderData: readAuthHint,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    if (query.isSuccess) writeAuthHint(query.data);
    if (query.isError && query.error?.status === 401) writeAuthHint(null);
  }, [query.isSuccess, query.isError, query.data, query.error]);
  return query;
}

export function SessionProvider({ me, children }) {
  const perms = useMemo(() => new Set(me?.perms || []), [me]);
  const can = useCallback((perm) => perms.has(perm), [perms]);
  const canAny = useCallback((...list) => list.some((perm) => perms.has(perm)), [perms]);

  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api.get("/api/workspaces"),
    enabled: Boolean(me),
    staleTime: 60_000,
  });
  const [stored, setStored] = useState(() => localStorage.getItem(WORKSPACE_KEY) || "");
  const items = workspaces.data?.items || [];
  const current = items.find((item) => item.id === stored) || items[0] || null;
  const workspaceId = current?.id || "";

  const setWorkspace = useCallback((id) => {
    localStorage.setItem(WORKSPACE_KEY, id);
    setStored(id);
  }, []);

  const value = useMemo(
    () => ({
      me,
      can,
      canAny,
      workspaces: items,
      workspace: current,
      workspaceId,
      workspacesLoading: !workspaces.data && workspaces.isLoading,
      setWorkspace,
    }),
    [me, can, canAny, items, current, workspaceId, workspaces.data, workspaces.isLoading, setWorkspace],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession outside SessionProvider");
  return value;
}

/** One EventSource for the whole console; any `change` refetches active queries (debounced). */
export function useLiveUpdates(enabled) {
  const client = useQueryClient();
  const timer = useRef(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return undefined;
    const source = new EventSource("/api/events/stream");
    const refresh = () => {
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        // Refresh in the background. placeholderData keeps the current page painted.
        client.invalidateQueries({
          predicate: (query) => query.queryKey[0] !== "auth-status" && query.queryKey[0] !== "ontology",
        });
      }, 500);
    };
    source.addEventListener("change", refresh);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    return () => {
      clearTimeout(timer.current);
      source.close();
    };
  }, [enabled, client]);
  return connected;
}

export function useOntology() {
  return useQuery({
    queryKey: ["ontology"],
    queryFn: () => api.get("/api/ontology"),
    staleTime: Infinity,
  });
}
