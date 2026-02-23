import Link from "next/link"
import { Plus } from "lucide-react"
import { Button } from "@/components/ui/button"

export function DashboardHeader() {
  return (
    <header className="flex items-center justify-between border-b border-border px-6 py-4">
      <h1 className="text-lg font-semibold tracking-tight text-foreground">
        Dashboard
      </h1>
      <Button asChild size="sm" className="gap-2">
        <Link href="/analyze">
          <Plus className="size-4" />
          New Analysis
        </Link>
      </Button>
    </header>
  )
}
