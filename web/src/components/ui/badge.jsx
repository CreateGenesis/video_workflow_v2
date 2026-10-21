import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-transparent bg-secondary text-secondary-foreground",
        success: "border-transparent bg-emerald-100 text-emerald-900",
        warning: "border-transparent bg-amber-100 text-amber-900",
        danger: "border-transparent bg-red-100 text-red-900",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

const STATUS = {
  已成片: "success",
  排队: "warning",
  提交不明: "warning",
  失败: "danger",
  未生成: "default",
  在线: "success",
  离线: "default",
};

export function Badge({ className, variant, status, ...props }) {
  return <span className={cn(badgeVariants({ variant: variant || STATUS[status] || "default" }), className)} {...props} />;
}
