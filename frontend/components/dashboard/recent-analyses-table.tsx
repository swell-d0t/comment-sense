import Link from "next/link"
import { ArrowRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { SentimentBadge } from "@/components/sentiment-badge"

const recentAnalyses = [
  {
    id: "1",
    label: "Product Launch Post",
    date: "Feb 20, 2026",
    comments: 342,
    positive: 68,
    negative: 12,
    sentiment: "positive" as const,
  },
  {
    id: "2",
    label: "Behind the Scenes Reel",
    date: "Feb 18, 2026",
    comments: 189,
    positive: 51,
    negative: 22,
    sentiment: "neutral" as const,
  },
  {
    id: "3",
    label: "Customer Testimonial",
    date: "Feb 15, 2026",
    comments: 97,
    positive: 82,
    negative: 5,
    sentiment: "positive" as const,
  },
  {
    id: "4",
    label: "Price Change Announcement",
    date: "Feb 12, 2026",
    comments: 521,
    positive: 25,
    negative: 48,
    sentiment: "negative" as const,
  },
  {
    id: "5",
    label: "Team Photo Friday",
    date: "Feb 10, 2026",
    comments: 64,
    positive: 73,
    negative: 8,
    sentiment: "positive" as const,
  },
]

export function RecentAnalysesTable() {
  return (
    <Card className="flex flex-1 flex-col py-4">
      <CardHeader className="pb-0">
        <CardTitle className="text-sm font-medium text-foreground">
          Recent Analyses
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1">
        <Table>
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Post Label
              </TableHead>
              <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Date
              </TableHead>
              <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground text-right">
                Comments
              </TableHead>
              <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground text-right">
                Positive %
              </TableHead>
              <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground text-right">
                Negative %
              </TableHead>
              <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Sentiment
              </TableHead>
              <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {recentAnalyses.map((analysis) => (
              <TableRow key={analysis.id} className="border-border">
                <TableCell className="font-medium text-foreground">
                  {analysis.label}
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {analysis.date}
                </TableCell>
                <TableCell className="text-right font-mono text-sm text-foreground">
                  {analysis.comments.toLocaleString()}
                </TableCell>
                <TableCell className="text-right font-mono text-sm text-sentiment-positive">
                  {analysis.positive}%
                </TableCell>
                <TableCell className="text-right font-mono text-sm text-sentiment-negative">
                  {analysis.negative}%
                </TableCell>
                <TableCell>
                  <SentimentBadge sentiment={analysis.sentiment} />
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="sm"
                    asChild
                    className="gap-1 text-muted-foreground hover:text-foreground"
                  >
                    <Link href={`/analyze?id=${analysis.id}`}>
                      Open
                      <ArrowRight className="size-3" />
                    </Link>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
