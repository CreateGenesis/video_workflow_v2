import { createContext, useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router";
import { AlertTriangle, ArrowLeft, Check, ChevronRight, Copy, Inbox, RefreshCw, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { Skeleton, Tooltip } from "@/components/ui/misc";
import { toast } from "@/components/ui/toast";
import { uiFlags } from "@/lib/api";
import { absoluteTime, pretty, relativeTime, yuan } from "@/lib/format";
import { RUN_STATUS, TASK_STATUS, VERSION_STATUS, statusOf } from "@/lib/labels";
import { cn } from "@/lib/utils";

/* ---------- page chrome ---------- */

export function PageHeader({ title, description, actions, back, meta, className }) {
  return (
    <div className={cn("mb-5 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between", className)}>
      <div className="min-w-0">
        {back ? (
          <Link to={back.to} className="mb-1.5 inline-flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-3.5" />
            {back.label}
          </Link>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="truncate text-xl font-semibold tracking-tight">{title}</h1>
          {meta}
        </div>
        {description ? <p className="mt-1 text-[13px] text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function Section({ title, description, actions, children, className }) {
  return (
    <section className={cn("space-y-3", className)}>
      {title || actions ? (
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            {title ? <h2 className="text-[15px] font-semibold">{title}</h2> : null}
            {description ? <p className="text-[13px] text-muted-foreground">{description}</p> : null}
          </div>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/* ---------- status ---------- */

export function TaskStatus({ status, className }) {
  const meta = statusOf(TASK_STATUS, status);
  const live = ["leased", "running", "submitting", "submitted"].includes(status);
  return (
    <Badge tone={meta.tone} dot pulse={live} className={className}>
      {meta.label}
    </Badge>
  );
}

export function RunStatus({ status, className }) {
  const meta = statusOf(RUN_STATUS, status);
  return (
    <Badge tone={meta.tone} dot pulse={status === "running"} className={className}>
      {meta.label}
    </Badge>
  );
}

export function VersionStatus({ status }) {
  const meta = statusOf(VERSION_STATUS, status);
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

/* ---------- time & money ---------- */

let tick = Date.now();
const tickListeners = new Set();
setInterval(() => {
  tick = Date.now();
  for (const listener of tickListeners) listener();
}, 30_000);

function useNow() {
  return useSyncExternalStore(
    (listener) => {
      tickListeners.add(listener);
      return () => tickListeners.delete(listener);
    },
    () => tick,
  );
}

export function Time({ value, className }) {
  const now = useNow();
  if (!value) return <span className={cn("text-muted-foreground", className)}>—</span>;
  return (
    <Tooltip content={absoluteTime(value)}>
      <time dateTime={String(value)} className={cn("tnum whitespace-nowrap", className)}>
        {relativeTime(value, Math.max(now, Date.now()))}
      </time>
    </Tooltip>
  );
}

export function Money({ value, className, digits }) {
  return <span className={cn("tnum whitespace-nowrap", className)}>{yuan(value, { digits })}</span>;
}

/* ---------- states ---------- */

export function EmptyState({ icon: Icon = Inbox, title, description, action, className, compact }) {
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-lg border border-dashed bg-card/60 px-6 text-center", compact ? "py-8" : "py-14", className)}>
      <div className="mb-3 flex size-10 items-center justify-center rounded-full bg-muted">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">{title}</p>
      {description ? <p className="mt-1 max-w-md text-[13px] text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, retry, className }) {
  const forbidden = error?.status === 403;
  return (
    <div className={cn("flex items-start gap-3 rounded-lg border border-[#6a2424] bg-[#3a1717] px-4 py-3", className)} role="alert">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[#ff4444]" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-[#ff6e6e]">{forbidden ? "没有权限查看" : error?.status === 404 ? "没有找到" : "加载失败"}</p>
        <p className="mt-0.5 break-words text-[13px] text-[#ff9c9c]">{error?.message || String(error)}</p>
      </div>
      {retry && !forbidden ? (
        <Button size="xs" variant="outline" onClick={retry}>
          <RefreshCw />
          重试
        </Button>
      ) : null}
    </div>
  );
}

export function InlineError({ children, className }) {
  if (!children) return null;
  return (
    <p className={cn("flex items-start gap-1.5 rounded-md border border-[#6a2424] bg-[#3a1717] px-2.5 py-2 text-[13px] text-[#ff9c9c]", className)} role="alert">
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
      <span className="min-w-0 break-words">{children}</span>
    </p>
  );
}

export function Notice({ tone = "info", children, className, icon: Icon }) {
  const tones = {
    info: "border-[#1d4e72] bg-[#123044] text-[#64b5f6]",
    warn: "border-[#6a4a18] bg-[#3a2a12] text-[#ffa931]",
    success: "border-[#1f5a36] bg-[#14301f] text-[#81c784]",
  };
  return (
    <div className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]", tones[tone], className)}>
      {Icon ? <Icon className="mt-0.5 size-4 shrink-0" /> : null}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/** One still block. Several pulsing bars strobe while a list is loading. */
export function PageLoading({ label = "正在加载", className }) {
  return (
    <div className={cn("page-loading", className)} role="status" aria-live="polite">
      <span className="text-[13px] text-[#8a8a8a]">{label}</span>
    </div>
  );
}

export function Reveal({ children, className }) {
  return <div className={cn("page-reveal", className)}>{children}</div>;
}

export function SkeletonRows({ rows = 4, className }) {
  return <PageLoading className={className} />;
}

export function SkeletonCards({ count = 3, className }) {
  return <PageLoading className={className} />;
}

/** First load → skeleton, error with nothing to show → ErrorState, else children(data).
 * A disabled query (workspace not chosen yet) stays on the skeleton instead of flashing an empty list. */
export function QueryView({ query, skeleton, children }) {
  const shown = query.data;
  if (query.isError && !shown) return <ErrorState error={query.error} retry={() => query.refetch()} />;
  if (!shown) return skeleton ?? <PageLoading />;
  return <Reveal>{children(shown)}</Reveal>;
}

/* ---------- confirm ---------- */

const ConfirmContext = createContext(null);

export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const resolver = useRef(null);

  const confirm = useCallback((options) => {
    setNote("");
    setBusy(false);
    setFailure("");
    setState(options);
    return new Promise((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const close = (result) => {
    resolver.current?.(result);
    resolver.current = null;
    setState(null);
  };

  const accept = async () => {
    if (state?.noteRequired && !note.trim()) return;
    if (state?.action) {
      setBusy(true);
      setFailure("");
      uiFlags.confirmActive = true;
      try {
        await state.action(note);
      } catch (error) {
        setBusy(false);
        setFailure(error?.message || String(error));
        return;
      } finally {
        uiFlags.confirmActive = false;
      }
    }
    close(state?.withNote ? { note } : true);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={Boolean(state)} onOpenChange={(open) => (!open && !busy ? close(false) : null)}>
        {state ? (
          <DialogContent>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                {state.danger ? <AlertTriangle className="size-4 text-[#ff4444]" /> : null}
                {state.title}
              </DialogTitle>
              {state.description ? <DialogDescription className="whitespace-pre-line">{state.description}</DialogDescription> : null}
            </DialogHeader>
            {state.spends || state.body || state.withNote || failure ? (
              <DialogBody className="space-y-3">
                {state.spends ? (
                  <Notice tone="warn" icon={AlertTriangle}>
                    这个操作会调用付费供应商并产生花费{state.spends === true ? "" : `：${state.spends}`}。
                  </Notice>
                ) : null}
                {state.body}
                {state.withNote ? (
                  <Textarea
                    autoFocus
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder={state.notePlaceholder || "写下理由（可选）"}
                  />
                ) : null}
                {failure ? <InlineError>{failure}</InlineError> : null}
              </DialogBody>
            ) : null}
            <DialogFooter>
              <Button variant="outline" onClick={() => close(false)} disabled={busy}>
                取消
              </Button>
              <Button variant={state.danger ? "destructive" : "default"} onClick={accept} loading={busy} disabled={state.noteRequired && !note.trim()}>
                {state.confirmText || "确定"}
              </Button>
            </DialogFooter>
          </DialogContent>
        ) : null}
      </Dialog>
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  return useContext(ConfirmContext);
}

/* ---------- small pieces ---------- */

export function CopyButton({ value, label = "复制", size = "xs", variant = "outline" }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const area = document.createElement("textarea");
        area.value = value;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
      }
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
      toast.error("复制失败", "请手动选中后复制");
    }
  };
  return (
    <Button size={size} variant={variant} onClick={copy} type="button">
      {done ? <Check /> : <Copy />}
      {done ? "已复制" : label}
    </Button>
  );
}

export function JsonView({ value, className, maxHeight = "28rem" }) {
  return (
    <pre
      className={cn("overflow-auto rounded-md border border-[#4e4e4e] bg-[#171718] p-3 text-xs leading-relaxed text-[#ddd]", className)}
      style={{ maxHeight }}
    >
      {typeof value === "string" ? value : pretty(value)}
    </pre>
  );
}

/** <details>-based collapsible with a styled summary. */
export function Collapsible({ title, children, defaultOpen = false, className, extra }) {
  return (
    <details className={cn("group rounded-md border bg-card", className)} open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-[13px] font-medium text-[#ddd] select-none [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-3.5 text-muted-foreground transition-transform group-open:rotate-90" />
        <span className="min-w-0 flex-1 truncate">{title}</span>
        {extra}
      </summary>
      <div className="border-t px-3 py-2.5">{children}</div>
    </details>
  );
}

export function KeyValues({ items, className }) {
  return (
    <dl className={cn("grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]", className)}>
      {items
        .filter(Boolean)
        .map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="whitespace-nowrap text-muted-foreground">{key}</dt>
            <dd className="min-w-0 break-words">{value ?? "—"}</dd>
          </div>
        ))}
    </dl>
  );
}

export function TagInput({ value = [], onChange, placeholder = "输入后按回车添加", max, invalid, id }) {
  const [text, setText] = useState("");
  const add = () => {
    const parts = text
      .split(/[\n,，]/)
      .map((part) => part.trim())
      .filter(Boolean);
    if (!parts.length) return;
    const next = [...value, ...parts].slice(0, max || Infinity);
    onChange(next);
    setText("");
  };
  return (
    <div
      className={cn(
        "flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-md border border-input bg-card px-2 py-1.5 shadow-xs focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/15",
        invalid && "border-red-400",
      )}
    >
      {value.map((tag, index) => (
        <span key={`${tag}-${index}`} className="inline-flex items-center gap-1 rounded bg-accent px-1.5 py-0.5 text-[13px] text-accent-foreground">
          {tag}
          <button type="button" className="rounded hover:bg-[#353535]" onClick={() => onChange(value.filter((_, i) => i !== index))} aria-label={`删除 ${tag}`}>
            <X className="size-3" />
          </button>
        </span>
      ))}
      {max && value.length >= max ? null : (
        <input
          id={id}
          className="min-w-32 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-[#8a8a8a]"
          value={text}
          placeholder={value.length ? "" : placeholder}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              add();
            } else if (event.key === "Backspace" && !text && value.length) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={add}
        />
      )}
    </div>
  );
}

export function StatCard({ label, value, hint, icon: Icon, tone, to }) {
  const body = (
    <div className={cn("rounded-lg border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-colors", to && "hover:border-[#c8cfdb]")}>
      <div className="flex items-center justify-between">
        <p className="text-[13px] text-muted-foreground">{label}</p>
        {Icon ? <Icon className={cn("size-4 text-muted-foreground", tone === "amber" && "text-[#f79009]", tone === "blue" && "text-primary")} /> : null}
      </div>
      <p className="tnum mt-1.5 text-2xl font-semibold tracking-tight">{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
  return to ? <Link to={to}>{body}</Link> : body;
}

export function useDocumentTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · cvgen` : "cvgen 控制台";
  }, [title]);
}

export function IdText({ id, className }) {
  if (!id) return null;
  return <code className={cn("rounded bg-muted px-1 py-0.5 text-[11px] text-muted-foreground", className)}>{id}</code>;
}
