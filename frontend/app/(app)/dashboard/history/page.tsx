"use client"

import { useEffect, useState } from "react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { ResultsUI } from "@/components/analyze/results-ui"
import { LoadingSpinner } from "@/components/loading-spinner"
import { ErrorBanner } from "@/components/error-banner"
import {
  fetchHistory,
  fetchAnalysisDetail,
  type AnalysisSummary,
  type AnalysisResult,
} from "@/lib/api"

export default function HistoryPage() {
  const [items, setItems] = useState<AnalysisSummary[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [selectedResult, setSelectedResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true

    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const data = await fetchHistory()
        if (!isMounted) return
        setItems(data)
      } catch (err) {
        if (!isMounted) return
        if (err instanceof Error) {
          setError(err.message)
        } else {
          setError("Failed to load history. Please try again.")
        }
      } finally {
        if (isMounted) setLoading(false)
      }
    }

    load()

    return () => {
      isMounted = false
    }
  }, [])

  const handleRowClick = async (id: string) => {
    try {
      setSelectedId(id)
      setDetailLoading(true)
      setError(null)
      const result = await fetchAnalysisDetail(id)
      setSelectedResult(result)
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message)
      } else {
        setError("Failed to load analysis details. Please try again.")
      }
      setSelectedResult(null)
    } finally {
      setDetailLoading(false)
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-6 px-6 py-6">
      <header className="flex items-center justify-between">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          History
        </h1>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1.5fr)]">
        <Card className="flex flex-col">
          <CardHeader className="pb-0">
            <CardTitle className="text-sm font-medium text-foreground">
              Previous Analyses
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 pt-4">
            {loading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <LoadingSpinner
                  size="sm"
                  className="border-primary-foreground/30 border-t-primary-foreground"
                />
                Loading history…
              </div>
            )}

            {error && (
              <ErrorBanner
                message={error}
                className="mb-4"
                onDismiss={() => setError(null)}
              />
            )}

            {!loading && items.length === 0 && !error && (
              <p className="text-sm text-muted-foreground">
                No analyses yet. Run your first analysis to see it here.
              </p>
            )}

            {items.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow className="border-border hover:bg-transparent">
                    <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                      Label
                    </TableHead>
                    <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                      Date
                    </TableHead>
                    <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground text-right">
                      Comments
                    </TableHead>
                    <TableHead className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
                      Sentiment
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow
                      key={item.id}
                      className="cursor-pointer border-border hover:bg-muted/40"
                      onClick={() => handleRowClick(item.id)}
                      data-selected={item.id === selectedId}
                    >
                      <TableCell className="text-sm text-foreground">
                        {item.label}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-muted-foreground">
                        {new Date(item.createdAt).toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right text-sm font-mono text-foreground">
                        {item.totalComments.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-sm capitalize text-foreground">
                        {item.overallSentiment}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="flex flex-col">
          <CardHeader className="pb-0">
            <CardTitle className="text-sm font-medium text-foreground">
              Analysis Details
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 pt-4">
            {detailLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <LoadingSpinner
                  size="sm"
                  className="border-primary-foreground/30 border-t-primary-foreground"
                />
                Loading analysis…
              </div>
            )}

            {!detailLoading && !selectedResult && (
              <p className="text-sm text-muted-foreground">
                Select a row from the table to view full analysis details.
              </p>
            )}

            {selectedResult && <ResultsUI result={selectedResult} />}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

