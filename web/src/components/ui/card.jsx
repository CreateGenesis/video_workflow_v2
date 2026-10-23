import { cn } from "@/lib/utils";

export function Card({ className, ...props }) {
  return <div className={cn("rounded-lg border border-[#4e4e4e] bg-[#262729] text-card-foreground shadow-[0_0_0.5rem_rgb(16_16_16/0.5)]", className)} {...props} />;
}

export function CardHeader({ className, ...props }) {
  return <div className={cn("flex items-start justify-between gap-3 border-b px-4 py-3", className)} {...props} />;
}

export function CardTitle({ className, ...props }) {
  return <h3 className={cn("text-[15px] font-semibold leading-6", className)} {...props} />;
}

export function CardDescription({ className, ...props }) {
  return <p className={cn("text-[13px] text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }) {
  return <div className={cn("p-4", className)} {...props} />;
}

export function CardFooter({ className, ...props }) {
  return <div className={cn("flex items-center justify-end gap-2 border-t px-4 py-3", className)} {...props} />;
}
