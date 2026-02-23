import { Instagram } from "lucide-react"
import { Button } from "@/components/ui/button"

export default function LoginPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4">
      <div className="flex w-full max-w-sm flex-col items-center gap-8">
        {/* Logo */}
        <div className="flex flex-col items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="flex size-9 items-center justify-center rounded-lg border border-border bg-card">
              <svg
                width="18"
                height="18"
                viewBox="0 0 18 18"
                fill="none"
                className="text-foreground"
              >
                <path
                  d="M9 1.5C4.86 1.5 1.5 4.86 1.5 9s3.36 7.5 7.5 7.5 7.5-3.36 7.5-7.5S13.14 1.5 9 1.5Zm0 13.5c-3.31 0-6-2.69-6-6s2.69-6 6-6 6 2.69 6 6-2.69 6-6 6Z"
                  fill="currentColor"
                  opacity="0.3"
                />
                <path
                  d="M9 4.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Zm2.03 3.22-2.25 3a.75.75 0 0 1-1.2.02l-1.125-1.5a.375.375 0 0 1 .6-.45l.83 1.1 1.92-2.56a.375.375 0 1 1 .6.45l.625-.07Z"
                  fill="currentColor"
                />
              </svg>
            </div>
            <span className="text-xl font-semibold tracking-tight text-foreground">
              CommentSense
            </span>
          </div>
          <p className="text-center text-sm text-muted-foreground leading-relaxed">
            Understand what your audience really thinks.
          </p>
        </div>

        {/* Login Card */}
        <div className="w-full rounded-xl border border-border bg-card p-6">
          <Button
            className="w-full gap-2"
            size="lg"
          >
            <Instagram className="size-4" />
            Continue with Instagram
          </Button>
        </div>

        {/* Disclaimer */}
        <p className="max-w-xs text-center text-xs text-muted-foreground leading-relaxed">
          CommentSense only analyzes comments on your own posts. We never access
          other accounts.
        </p>

        {/* Footer */}
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <a href="#" className="hover:text-foreground transition-colors">
            Privacy Policy
          </a>
          <span className="text-border">|</span>
          <a href="#" className="hover:text-foreground transition-colors">
            Terms
          </a>
        </div>
      </div>
    </div>
  )
}
