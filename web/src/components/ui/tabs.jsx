import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export function Tabs({ className, ...props }) {
  return <TabsPrimitive.Root className={cn("flex flex-col gap-4", className)} {...props} />;
}

export function TabsList({ className, ...props }) {
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <TabsPrimitive.List className={cn("flex min-w-max items-center gap-1 border-b", className)} {...props} />
    </div>
  );
}

export function TabsTrigger({ className, children, count, ...props }) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "relative -mb-px inline-flex h-9 items-center gap-1.5 whitespace-nowrap border-b-2 border-transparent px-2.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none data-[state=active]:border-primary data-[state=active]:text-foreground",
        className,
      )}
      {...props}
    >
      {children}
      {count ? <span className="tnum rounded bg-muted px-1.5 text-xs text-muted-foreground">{count}</span> : null}
    </TabsPrimitive.Trigger>
  );
}

export function TabsContent({ className, ...props }) {
  return <TabsPrimitive.Content className={cn("focus-visible:outline-none", className)} {...props} />;
}
