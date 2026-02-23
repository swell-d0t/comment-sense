import { cn } from "@/lib/utils"

interface ConfidenceBarProps {
  value: number // 0-1 float
  className?: string
}

export function ConfidenceBar({ value, className }: ConfidenceBarProps) {
  const percentage = Math.round(value * 100)

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-1.5 w-16 rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-foreground/70 transition-all"
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-xs font-mono text-muted-foreground">{percentage}%</span>
    </div>
  )
}
