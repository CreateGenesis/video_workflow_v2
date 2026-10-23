import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

const SessionContext = createContext(null);
const WORKSPACE_KEY = "cvgen.workspace";

export function useAuthStatus() {
  return useQuery({
    queryKey: ["auth-status"],
    queryFn: () => api.get("/api/auth/status", { quiet401: true }),
    staleTime: 60_000,
  });
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
      workspaceId: current?.id || "",
      workspacesLoading: workspaces.isLoading,
      setWorkspace,
    }),
    [me, can, canAny, items, current, workspaces.isLoading, setWorkspace],
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
        client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "auth-status" && query.queryKey[0] !== "ontology" });
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
