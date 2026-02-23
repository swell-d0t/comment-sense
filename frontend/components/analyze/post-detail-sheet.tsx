"use client"

import { useState } from "react"
import { Calendar, MessageSquare, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { ResultsUI } from "@/components/analyze/results-ui"
import { LoadingSpinner } from "@/components/loading-spinner"
import { ErrorBanner } from "@/components/error-banner"
import {
  analyzeComments,
  fetchPostComments,
  type AnalysisResult,
  ApiError,
} from "@/lib/api"

interface Post {
  id: string
  thumbnailUrl: string
  caption: string
  commentCount: number
  date: string
}

interface PostDetailSheetProps {
  post: Post | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function PostDetailSheet({
  post,
  open,
  onOpenChange,
}: PostDetailSheetProps) {
  const [analyzing, setAnalyzing] = useState(false)
  const [showResults, setShowResults] = useState(false)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleAnalyze = async () => {
    if (!post) return

    try {
      setAnalyzing(true)
      setError(null)

      const comments = await fetchPostComments(post.id)
      const rawText = comments.map((c) => c.text).join("\n")

      const analysis = await analyzeComments(
        post.caption || "Instagram Post",
        rawText
      )

      setResult(analysis)
      setShowResults(true)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError("Failed to fetch and analyze comments. Please try again.")
      }
      setResult(null)
      setShowResults(false)
    } finally {
      setAnalyzing(false)
    }
  }

  const handleOpenChange = (isOpen: boolean) => {
    if (!isOpen) {
      setAnalyzing(false)
      setShowResults(false)
      setResult(null)
      setError(null)
    }
    onOpenChange(isOpen)
  }

  if (!post) return null

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-xl lg:max-w-2xl p-0"
      >
        <ScrollArea className="h-full">
          <div className="flex flex-col gap-6 p-6">
            <SheetHeader className="p-0">
              <SheetTitle className="text-foreground">Post Details</SheetTitle>
              <SheetDescription className="sr-only">
                View post details and analyze comments
              </SheetDescription>
            </SheetHeader>

            {/* Post Info */}
            <div className="flex flex-col gap-3">
              <div className="aspect-video rounded-lg bg-muted flex items-center justify-center">
                <div className="flex flex-col items-center gap-2 text-muted-foreground">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="2" y="2" width="20" height="20" rx="5" />
                    <circle cx="12" cy="12" r="5" />
                    <circle cx="18" cy="6" r="1.5" />
                  </svg>
                </div>
              </div>
              <p className="text-sm text-foreground leading-relaxed">
                {post.caption}
              </p>
              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                <span className="flex items-center gap-1 font-mono">
                  <MessageSquare className="size-3" />
                  {post.commentCount} comments
                </span>
                <span className="flex items-center gap-1 font-mono">
                  <Calendar className="size-3" />
                  {post.date}
                </span>
              </div>
            </div>

            <Separator className="bg-border" />

            {error && (
              <ErrorBanner
                message={error}
                className="mt-2"
                onDismiss={() => setError(null)}
              />
            )}

            {/* Analyze Button */}
            {!showResults && (
              <Button
                onClick={handleAnalyze}
                disabled={analyzing}
                size="lg"
                className="gap-2 w-full"
              >
                {analyzing ? (
                  <>
                    <LoadingSpinner size="sm" className="border-primary-foreground/30 border-t-primary-foreground" />
                    Analyzing Comments...
                  </>
                ) : (
                  <>
                    <Sparkles className="size-4" />
                    Fetch & Analyze Comments
                  </>
                )}
              </Button>
            )}

            {/* Results */}
            {showResults && result && <ResultsUI result={result} />}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}
