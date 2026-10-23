import { useSyncExternalStore } from "react";
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

let items = [];
let nextId = 1;
const listeners = new Set();

function emit() {
  for (const listener of listeners) listener();
}

function push(kind, title, description, timeout) {
  const id = nextId++;
  items = [...items.slice(-3), { id, kind, title, description }];
  emit();
  setTimeout(() => dismiss(id), timeout);
  return id;
}

export function dismiss(id) {
  items = items.filter((item) => item.id !== id);
  emit();
}

export const toast = {
  success: (title, description) => push("success", title, description, 3500),
  error: (title, description) => push("error", title, description, 7000),
  info: (title, description) => push("info", title, description, 4000),
};

/** Use as onError for mutations: shows the server's detail. */
export function toastError(title = "操作失败") {
  return (error) => toast.error(title, error?.message || String(error));
}

export function Toaster() {
  const list = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => items,
  );
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[70] flex w-[calc(100vw-2rem)] max-w-sm flex-col gap-2" role="status" aria-live="polite">
      {list.map((item) => (
        <div
          key={item.id}
          className={cn(
            "pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-card px-3.5 py-3 shadow-lg",
            item.kind === "error" && "border-[#6a2424] bg-[#3a1717]",
            item.kind === "success" && "border-[#1f5a36]",
          )}
        >
          {item.kind === "success" ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-[#81c784]" />
          ) : item.kind === "error" ? (
            <XCircle className="mt-0.5 size-4 shrink-0 text-[#ff4444]" />
          ) : (
            <Info className="mt-0.5 size-4 shrink-0 text-primary" />
          )}
          <div className="min-w-0 flex-1">
            <p className={cn("text-sm font-medium", item.kind === "error" && "text-[#ff6e6e]")}>{item.title}</p>
            {item.description ? <p className={cn("mt-0.5 break-words text-[13px] text-muted-foreground", item.kind === "error" && "text-[#ff9c9c]")}>{item.description}</p> : null}
          </div>
          <button className="rounded p-0.5 text-muted-foreground hover:bg-muted" onClick={() => dismiss(item.id)} aria-label="关闭">
            <X className="size-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
