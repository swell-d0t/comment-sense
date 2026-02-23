"use client"

import { useState } from "react"
import { AlertCircle, X } from "lucide-react"
import { cn } from "@/lib/utils"

interface ErrorBannerProps {
  code?: number | string
  message: string
  className?: string
  onDismiss?: () => void
}

export function ErrorBanner({ code, message, className, onDismiss }: ErrorBannerProps) {
  const [dismissed, setDismissed] = useState(false)

  if (dismissed) return null

  const handleDismiss = () => {
    setDismissed(true)
    onDismiss?.()
  }

  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-lg border border-sentiment-negative/30 bg-sentiment-negative/10 px-4 py-3",
        className
      )}
    >
      <AlertCircle className="size-4 shrink-0 text-sentiment-negative mt-0.5" />
      <div className="flex-1 text-sm">
        {code && (
          <span className="font-mono text-sentiment-negative mr-2">
            {code}
          </span>
        )}
        <span className="text-foreground">{message}</span>
      </div>
      <button
        onClick={handleDismiss}
        className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
        aria-label="Dismiss error"
      >
        <X className="size-4" />
      </button>
    </div>
  )
}
