import { useState } from "react";
import { Download, FileText, Film, ImageOff, Music, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { downloadUrl } from "@/lib/api";
import { bytes, duration } from "@/lib/format";
import { cn } from "@/lib/utils";

export function mediaKind(artifact) {
  if (!artifact) return "none";
  const mime = artifact.mime || "";
  if (artifact.kind === "video" || mime.startsWith("video/")) return "video";
  if (artifact.kind === "image" || mime.startsWith("image/")) return "image";
  if (artifact.kind === "audio" || mime.startsWith("audio/")) return "audio";
  return "file";
}

/** Small square-ish preview. Click opens a large viewer with a download link. */
export function Thumb({ artifact, url, className, label, selected, onClick, aspect = "aspect-video" }) {
  const [open, setOpen] = useState(false);
  const [broken, setBroken] = useState(false);
  const item = artifact || (url ? { url, kind: "image" } : null);
  const kind = mediaKind(item);
  const click = onClick || (() => setOpen(true));
  return (
    <>
      <button
        type="button"
        onClick={click}
        className={cn(
          "group relative block w-full overflow-hidden rounded-md border bg-[#353535] text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          aspect,
          selected && "ring-2 ring-primary ring-offset-1",
          className,
        )}
        title={label || item?.label}
      >
        {!item ? (
          <span className="flex size-full items-center justify-center text-muted-foreground">
            <ImageOff className="size-5" />
          </span>
        ) : kind === "image" && !broken ? (
          <img src={item.url} alt={label || item.label || ""} loading="lazy" className="size-full object-cover" onError={() => setBroken(true)} />
        ) : kind === "video" ? (
          <>
            <video src={`${item.url}#t=0.1`} preload="metadata" muted playsInline className="size-full object-cover" />
            <span className="absolute inset-0 flex items-center justify-center">
              <span className="flex size-8 items-center justify-center rounded-full bg-black/55 text-white transition-transform group-hover:scale-110">
                <Play className="ml-0.5 size-4" />
              </span>
            </span>
          </>
        ) : (
          <span className="flex size-full flex-col items-center justify-center gap-1 text-muted-foreground">
            {kind === "audio" ? <Music className="size-5" /> : broken ? <ImageOff className="size-5" /> : <FileText className="size-5" />}
            <span className="max-w-full truncate px-2 text-[11px]">{item.label || "文件"}</span>
          </span>
        )}
        {label ? <span className="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/60 to-transparent px-1.5 pb-1 pt-3 text-[11px] text-white">{label}</span> : null}
      </button>
      {item ? <MediaDialog open={open} onOpenChange={setOpen} artifact={item} title={label || item.label} /> : null}
    </>
  );
}

export function MediaDialog({ open, onOpenChange, artifact, title }) {
  const kind = mediaKind(artifact);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide>
        <DialogHeader>
          <DialogTitle className="truncate">{title || "预览"}</DialogTitle>
        </DialogHeader>
        <DialogBody>
          <div className="flex items-center justify-center overflow-hidden rounded-md bg-[#101828]">
            {kind === "video" ? (
              <video src={artifact.url} controls autoPlay playsInline className="max-h-[65vh] w-full" />
            ) : kind === "image" ? (
              <img src={artifact.url} alt={title || ""} className="max-h-[65vh] object-contain" />
            ) : kind === "audio" ? (
              <audio src={artifact.url} controls className="m-6 w-full" />
            ) : (
              <p className="p-10 text-sm text-white/70">这个文件不能在网页里预览，请下载查看。</p>
            )}
          </div>
          <MediaMeta artifact={artifact} className="mt-2" />
        </DialogBody>
        <DialogFooter>
          <Button asChild variant="outline">
            <a href={downloadUrl(artifact.url)}>
              <Download />
              下载
            </a>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MediaMeta({ artifact, className }) {
  if (!artifact) return null;
  const parts = [];
  if (artifact.width && artifact.height) parts.push(`${artifact.width}×${artifact.height}`);
  if (artifact.duration) parts.push(duration(artifact.duration));
  if (artifact.bytes) parts.push(bytes(artifact.bytes));
  if (artifact.mime) parts.push(artifact.mime);
  return <p className={cn("tnum text-xs text-muted-foreground", className)}>{parts.join(" · ")}</p>;
}

export function VideoPlayer({ artifact, url, className, poster }) {
  const src = artifact?.url || url;
  if (!src) {
    return (
      <div className={cn("flex aspect-video items-center justify-center rounded-md border border-dashed bg-muted text-muted-foreground", className)}>
        <div className="flex flex-col items-center gap-1 text-xs">
          <Film className="size-5" />
          还没有成片
        </div>
      </div>
    );
  }
  return <video src={src} poster={poster} controls preload="metadata" playsInline className={cn("aspect-video w-full rounded-md bg-black", className)} />;
}

export function DownloadLink({ artifact, url, children = "下载", className }) {
  const src = artifact?.url || url;
  if (!src) return null;
  return (
    <Button asChild size="xs" variant="outline" className={className}>
      <a href={downloadUrl(src)}>
        <Download />
        {children}
      </a>
    </Button>
  );
}
