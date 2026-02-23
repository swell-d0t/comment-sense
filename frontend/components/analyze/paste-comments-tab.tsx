"use client"

import { useState } from "react"
import { Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { ResultsUI } from "@/components/analyze/results-ui"
import { LoadingSpinner } from "@/components/loading-spinner"

export function PasteCommentsTab() {
  const [rawText, setRawText] = useState("")
  const [postLabel, setPostLabel] = useState("")
  const [analyzing, setAnalyzing] = useState(false)
  const [showResults, setShowResults] = useState(false)

  const handleAnalyze = () => {
    setAnalyzing(true)
    // Simulate analysis
    setTimeout(() => {
      setAnalyzing(false)
      setShowResults(true)
    }, 2000)
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="raw-comments" className="text-sm text-foreground">
            Raw Comments
          </Label>
          <Textarea
            id="raw-comments"
            placeholder="Paste your raw Instagram comments here — usernames, timestamps and everything. We'll clean it up."
            className="min-h-[200px] bg-muted border-border font-mono text-sm resize-y"
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
          />
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="post-label" className="text-sm text-muted-foreground">
            Post Label{" "}
            <span className="text-xs">(optional)</span>
          </Label>
          <Input
            id="post-label"
            placeholder="e.g. Product Launch Post"
            className="bg-muted border-border"
            value={postLabel}
            onChange={(e) => setPostLabel(e.target.value)}
          />
        </div>

        <Button
          onClick={handleAnalyze}
          disabled={analyzing || !rawText.trim()}
          size="lg"
          className="gap-2 w-fit"
        >
          {analyzing ? (
            <>
              <LoadingSpinner size="sm" className="border-primary-foreground/30 border-t-primary-foreground" />
              Analyzing...
            </>
          ) : (
            <>
              <Sparkles className="size-4" />
              Analyze
            </>
          )}
        </Button>
      </div>

      {showResults && <ResultsUI />}
    </div>
  )
}
