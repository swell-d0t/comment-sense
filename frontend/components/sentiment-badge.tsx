import { cn } from "@/lib/utils"

type Sentiment = "positive" | "neutral" | "negative"

interface SentimentBadgeProps {
  sentiment: Sentiment
  className?: string
}

const sentimentConfig: Record<Sentiment, { label: string; classes: string }> = {
  positive: {
    label: "Positive",
    classes: "bg-sentiment-positive/15 text-sentiment-positive border-sentiment-positive/25",
  },
  neutral: {
    label: "Neutral",
    classes: "bg-sentiment-neutral/15 text-sentiment-neutral border-sentiment-neutral/25",
  },
  negative: {
    label: "Negative",
    classes: "bg-sentiment-negative/15 text-sentiment-negative border-sentiment-negative/25",
  },
}

export function SentimentBadge({ sentiment, className }: SentimentBadgeProps) {
  const config = sentimentConfig[sentiment]

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium font-mono",
        config.classes,
        className
      )}
    >
      {config.label}
    </span>
  )
}
