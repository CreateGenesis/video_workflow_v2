import * as LabelPrimitive from "@radix-ui/react-label";
import { cn } from "@/lib/utils";

export function Label({ className, ...props }) {
  return <LabelPrimitive.Root className={cn("text-[13px] font-medium leading-none text-[#ddd]", className)} {...props} />;
}

/** Label + control + hint/error, stacked. */
export function Field({ label, htmlFor, hint, error, required, className, children }) {
  return (
    <div className={cn("grid gap-1.5", className)}>
      {label ? (
        <Label htmlFor={htmlFor}>
          {label}
          {required ? <span className="ml-0.5 text-[#ff4444]">*</span> : null}
        </Label>
      ) : null}
      {children}
      {error ? <p className="text-xs text-[#ff4444]">{error}</p> : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
