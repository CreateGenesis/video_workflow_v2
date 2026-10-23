import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

const field =
  "w-full rounded-md border border-[#4e4e4e] bg-[#222] px-3 text-sm text-[#ddd] shadow-xs transition-colors placeholder:text-[#666] focus-visible:border-[#0b8ce9] focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-[#0b8ce9]/30 disabled:cursor-not-allowed disabled:bg-[#171718] disabled:opacity-70 aria-invalid:border-[#ff4444] aria-invalid:ring-[#ff4444]/20";

export function Input({ className, ...props }) {
  return <input className={cn(field, "h-9 py-1", className)} {...props} />;
}

export function Textarea({ className, ...props }) {
  return <textarea className={cn(field, "min-h-20 py-2 leading-relaxed", className)} {...props} />;
}

/** Styled native select: accessible, works on phones, no portal. options: [{value,label}] or children. */
export function Select({ className, options, children, placeholder, ...props }) {
  return (
    <div className={cn("relative", className)}>
      <select className={cn(field, "h-9 appearance-none pr-8")} {...props}>
        {placeholder !== undefined ? <option value="">{placeholder}</option> : null}
        {options
          ? options.map((option) => (
              <option key={option.value} value={option.value} disabled={option.disabled}>
                {option.label}
              </option>
            ))
          : children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}
