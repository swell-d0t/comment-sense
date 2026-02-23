import { BarChart3, MessageSquare, TrendingUp } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"

const stats = [
  {
    label: "Total Analyses Run",
    value: "24",
    icon: BarChart3,
    change: "+3 this week",
  },
  {
    label: "Comments Analyzed",
    value: "12,847",
    icon: MessageSquare,
    change: "Lifetime",
  },
  {
    label: "Avg Sentiment Score",
    value: "72%",
    icon: TrendingUp,
    change: "Positive",
  },
]

export function StatsGrid() {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {stats.map((stat) => (
        <Card key={stat.label} className="py-4">
          <CardContent className="flex items-start justify-between">
            <div className="flex flex-col gap-1">
              <span className="text-xs font-mono text-muted-foreground uppercase tracking-wider">
                {stat.label}
              </span>
              <span className="text-2xl font-semibold tracking-tight text-foreground">
                {stat.value}
              </span>
              <span className="text-xs text-muted-foreground">
                {stat.change}
              </span>
            </div>
            <div className="flex size-9 items-center justify-center rounded-md bg-muted">
              <stat.icon className="size-4 text-muted-foreground" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
