import { cn } from "@/lib/utils";

const TONES = {
  gray: "bg-[#353535] text-[#ddd] ring-[#4e4e4e]",
  blue: "bg-[#123044] text-[#64b5f6] ring-[#1d4e72]",
  sky: "bg-[#123044] text-[#64b5f6] ring-[#1d4e72]",
  amber: "bg-[#3a2a12] text-[#ffa931] ring-[#6a4a18]",
  orange: "bg-[#3a2218] text-[#ff9c6e] ring-[#6a3a22]",
  green: "bg-[#14301f] text-[#81c784] ring-[#1f5a36]",
  red: "bg-[#3a1717] text-[#ff6e6e] ring-[#6a2424]",
  violet: "bg-[#2a2240] text-[#b39ddb] ring-[#4a3a6a]",
};

const DOTS = {
  gray: "bg-[#8a8a8a]",
  blue: "bg-[#0b8ce9]",
  sky: "bg-[#64b5f6]",
  amber: "bg-[#ffa931]",
  orange: "bg-[#ff6e6e]",
  green: "bg-[#81c784]",
  red: "bg-[#ff4444]",
  violet: "bg-[#b39ddb]",
};

export function Badge({ className, tone = "gray", dot = false, pulse = false, children, ...props }) {
  return (
    <span
      className={cn(
        "inline-flex h-5.5 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-1.5 text-xs font-medium ring-1 ring-inset",
        TONES[tone] || TONES.gray,
        className,
      )}
      {...props}
    >
      {dot ? (
        <span className="relative flex size-1.5">
          {pulse ? <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", DOTS[tone])} /> : null}
          <span className={cn("relative inline-flex size-1.5 rounded-full", DOTS[tone] || DOTS.gray)} />
        </span>
      ) : null}
      {children}
    </span>
  );
}
