"use client"

import { useMemo, useState } from "react"
import { Download, Search, ThumbsUp, ThumbsDown, MessageSquare, Shield, TrendingUp } from "lucide-react"
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { SentimentBadge } from "@/components/sentiment-badge"
import { ConfidenceBar } from "@/components/confidence-bar"
import { FlagPill } from "@/components/flag-pill"
import type { AnalysisResult, CommentAnalysis } from "@/lib/api"

interface ResultsUIProps {
  result: AnalysisResult | null
}

export function ResultsUI({ result }: ResultsUIProps) {
  const [searchQuery, setSearchQuery] = useState("")
  const [sentimentFilter, setSentimentFilter] = useState<string>("all")

  if (!result) {
    return null
  }

  const chartData = useMemo(() => {
    if (!result.totalComments || result.totalComments <= 0) {
      return []
    }

    const toPct = (value: number) =>
      Math.round((value / result.totalComments) * 100)

    return [
      { name: "Positive", value: toPct(result.positive), color: "oklch(0.70 0.15 150)" },
      { name: "Neutral", value: toPct(result.neutral), color: "oklch(0.55 0.005 260)" },
      { name: "Negative", value: toPct(result.negative), color: "oklch(0.55 0.2 25)" },
    ]
  }, [result])

  const comments: CommentAnalysis[] = result.comments || []

  const filteredComments = comments.filter((comment) => {
    const matchesSearch = comment.text
      .toLowerCase()
      .includes(searchQuery.toLowerCase())
    const matchesSentiment =
      sentimentFilter === "all" || comment.sentiment === sentimentFilter
    return matchesSearch && matchesSentiment
  })

  return (
    <div className="flex flex-col gap-6">
      {/* Stat Cards Row */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="py-4">
          <CardContent className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-md bg-muted">
              <MessageSquare className="size-4 text-muted-foreground" />
            </div>
            <div className="flex flex-col">
              <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Total Comments
              </span>
              <span className="text-xl font-semibold text-foreground">342</span>
            </div>
          </CardContent>
        </Card>

        <Card className="py-4">
          <CardContent className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-md bg-sentiment-positive/10">
              <TrendingUp className="size-4 text-sentiment-positive" />
            </div>
            <div className="flex flex-col">
              <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Overall Sentiment
              </span>
              <span className="text-xl font-semibold text-sentiment-positive">
                Positive
              </span>
            </div>
          </CardContent>
        </Card>

        <Card className="py-4">
          <CardContent className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-md bg-muted">
              <Shield className="size-4 text-muted-foreground" />
            </div>
            <div className="flex flex-col">
              <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                Avg Confidence
              </span>
              <span className="text-xl font-semibold text-foreground">
                {Math.round(result.averageConfidence * 100)}%
              </span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Donut Chart */}
      <Card className="py-4">
        <CardContent>
          <div className="flex flex-col items-center gap-4 md:flex-row md:items-start md:gap-8">
              <div className="h-48 w-48 shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  {chartData.length > 0 && (
                    <Pie
                      data={chartData}
                      cx="50%"
                      cy="50%"
                      innerRadius={55}
                      outerRadius={80}
                      paddingAngle={3}
                      dataKey="value"
                      strokeWidth={0}
                    >
                      {chartData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                  )}
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.17 0.005 260)",
                      border: "1px solid oklch(0.26 0.005 260)",
                      borderRadius: "8px",
                      color: "oklch(0.95 0.005 260)",
                      fontSize: "12px",
                    }}
                    formatter={(value: number) => [`${value}%`, ""]}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-col gap-3">
              {chartData.map((entry) => (
                <div key={entry.name} className="flex items-center gap-3">
                  <div
                    className="size-3 rounded-sm"
                    style={{ backgroundColor: entry.color }}
                  />
                  <span className="text-sm text-muted-foreground w-16">
                    {entry.name}
                  </span>
                  <span className="text-sm font-mono font-medium text-foreground">
                    {entry.value}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Callout boxes */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="py-4 border-sentiment-positive/20">
          <CardContent>
            <div className="flex items-start gap-3">
              <ThumbsUp className="size-4 shrink-0 text-sentiment-positive mt-0.5" />
              <div className="flex flex-col gap-1">
                <span className="text-xs font-mono uppercase tracking-wider text-sentiment-positive">
                  Most Positive
                </span>
                <p className="text-sm text-foreground leading-relaxed">
                  {'"This product is absolutely incredible! Best purchase I\'ve made this year. Highly recommend to everyone."'}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="py-4 border-sentiment-negative/20">
          <CardContent>
            <div className="flex items-start gap-3">
              <ThumbsDown className="size-4 shrink-0 text-sentiment-negative mt-0.5" />
              <div className="flex flex-col gap-1">
                <span className="text-xs font-mono uppercase tracking-wider text-sentiment-negative">
                  Most Negative
                </span>
                <p className="text-sm text-foreground leading-relaxed">
                  {'"Terrible customer service. Waited 3 weeks for a response and still no resolution."'}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Comments Table */}
      <Card className="py-4">
        <CardContent className="flex flex-col gap-4">
          {/* Filters Row */}
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-3">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search comments..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 w-64 bg-muted border-border"
                />
              </div>
              <Select
                value={sentimentFilter}
                onValueChange={setSentimentFilter}
              >
                <SelectTrigger className="w-36 bg-muted border-border">
                  <SelectValue placeholder="All sentiments" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="positive">Positive</SelectItem>
                  <SelectItem value="neutral">Neutral</SelectItem>
                  <SelectItem value="negative">Negative</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button variant="outline" size="sm" className="gap-2 w-fit">
              <Download className="size-3.5" />
              Export CSV
            </Button>
          </div>

          {/* Table */}
          <Table>
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground w-[50%]">
                  Comment
                </TableHead>
                <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Sentiment
                </TableHead>
                <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Confidence
                </TableHead>
                <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                  Flags
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredComments.map((comment, index) => (
                <TableRow key={index} className="border-border">
                  <TableCell className="max-w-md">
                    <p className="line-clamp-2 text-sm text-foreground leading-relaxed">
                      {comment.text}
                    </p>
                  </TableCell>
                  <TableCell>
                    <SentimentBadge sentiment={comment.sentiment} />
                  </TableCell>
                  <TableCell>
                    <ConfidenceBar value={comment.confidence} />
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {comment.flags.length > 0
                        ? comment.flags.map((flag) => (
                            <FlagPill key={flag} flag={flag} />
                          ))
                        : <span className="text-xs text-muted-foreground">--</span>}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
