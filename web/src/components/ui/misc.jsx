import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/utils";

export function Switch({ className, ...props }) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-[#4e4e4e] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="pointer-events-none block size-4 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0" />
    </SwitchPrimitive.Root>
  );
}

export const TooltipProvider = TooltipPrimitive.Provider;

export function Tooltip({ content, children, side = "top" }) {
  if (!content) return children;
  return (
    <TooltipPrimitive.Root delayDuration={250}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={4}
          className="z-[60] max-w-xs rounded-md border border-[#4e4e4e] bg-[#171718] px-2 py-1 text-xs text-white shadow-md"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export function Skeleton({ className }) {
  return <div className={cn("skeleton rounded-md", className)} />;
}

export function Separator({ className }) {
  return <div className={cn("h-px w-full bg-border", className)} />;
}

export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownMenuTrigger = DropdownPrimitive.Trigger;

export function DropdownMenuContent({ className, align = "end", ...props }) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        align={align}
        sideOffset={4}
        className={cn("z-50 min-w-44 rounded-lg border bg-card p-1 shadow-lg", className)}
        {...props}
      />
    </DropdownPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, danger, ...props }) {
  return (
    <DropdownPrimitive.Item
      className={cn(
        "flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-muted data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:text-muted-foreground",
        danger && "text-[#ff6e6e] [&_svg]:text-[#ff6e6e]",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuLabel({ className, ...props }) {
  return <DropdownPrimitive.Label className={cn("px-2 py-1.5 text-xs text-muted-foreground", className)} {...props} />;
}

export function DropdownMenuSeparator() {
  return <DropdownPrimitive.Separator className="-mx-1 my-1 h-px bg-border" />;
}

export function Table({ className, children }) {
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full border-collapse text-sm", className)}>{children}</table>
    </div>
  );
}

export function THead({ children }) {
  return (
    <thead className="bg-[#171718] text-left text-xs font-medium text-muted-foreground [&_th]:h-9 [&_th]:whitespace-nowrap [&_th]:border-b [&_th]:border-[#4e4e4e] [&_th]:px-3 [&_th]:font-medium">
      {children}
    </thead>
  );
}

export function TBody({ children }) {
  return <tbody className="[&_td]:border-b [&_td]:border-[#4e4e4e] [&_td]:px-3 [&_td]:py-2.5 [&_tr:last-child_td]:border-b-0 [&_tr]:transition-colors hover:[&_tr]:bg-[#303030]">{children}</tbody>;
}

export function Progress({ value = 0, tone = "blue", className }) {
  const colors = { blue: "bg-primary", green: "bg-[#81c784]", amber: "bg-[#ffa931]", red: "bg-[#ff4444]", gray: "bg-[#8a8a8a]" };
  const width = Math.max(0, Math.min(100, Math.round((Number(value) || 0) * 100)));
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-[#171718]", className)}>
      <div className={cn("h-full rounded-full transition-[width] duration-500", colors[tone] || colors.blue)} style={{ width: `${width}%` }} />
    </div>
  );
}
