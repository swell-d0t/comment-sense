"use client"

import { useEffect } from "react"
import { useRouter, useSearchParams } from "next/navigation"

export default function AuthCallbackPage() {
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    const code = searchParams.get("code")
    const state = searchParams.get("state")

    const handleCallback = async () => {
      if (!code || !state) {
        router.replace("/login?error=missing_params")
        return
      }

      try {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/auth/callback`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
            body: JSON.stringify({ code, state }),
          }
        )

        if (!response.ok) {
          router.replace("/login?error=auth_failed")
          return
        }

        router.replace("/dashboard")
      } catch {
        router.replace("/login?error=network_error")
      }
    }

    handleCallback()
  }, [router, searchParams])

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3">
        <span className="text-sm font-medium text-foreground">
          Completing sign-in…
        </span>
        <span className="text-xs text-muted-foreground">
          Please wait while we connect your Instagram account.
        </span>
      </div>
    </div>
  )
}

