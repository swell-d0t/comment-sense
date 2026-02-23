import { cn } from "@/lib/utils"

interface FlagPillProps {
  flag: string
  className?: string
}

export function FlagPill({ flag, className }: FlagPillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm border border-border bg-muted/50 px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground leading-none",
        className
      )}
    >
      {flag}
    </span>
  )
}
