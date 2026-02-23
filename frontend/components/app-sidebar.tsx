"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  LayoutDashboard,
  ImageIcon,
  History,
  Settings,
  LogOut,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"

const navItems = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "My Posts", href: "/analyze", icon: ImageIcon },
  { label: "History", href: "/dashboard/history", icon: History },
  { label: "Settings", href: "/dashboard/settings", icon: Settings },
]

export function AppSidebar() {
  const pathname = usePathname()

  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      {/* Logo */}
      <div className="flex items-center gap-2 px-5 py-5">
        <div className="flex size-7 items-center justify-center rounded-md border border-sidebar-border bg-sidebar-accent">
          <svg
            width="14"
            height="14"
            viewBox="0 0 18 18"
            fill="none"
            className="text-sidebar-foreground"
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
        <span className="text-sm font-semibold tracking-tight text-sidebar-foreground">
          CommentSense
        </span>
      </div>

      <Separator className="bg-sidebar-border" />

      {/* Navigation */}
      <nav className="flex flex-1 flex-col gap-1 px-3 py-4">
        {navItems.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(item.href))

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
              )}
            >
              <item.icon className="size-4" />
              {item.label}
            </Link>
          )
        })}
      </nav>

      {/* Connected Account */}
      <div className="border-t border-sidebar-border px-3 py-4">
        <div className="flex items-center gap-3 rounded-md px-2 py-2">
          <Avatar className="size-8">
            <AvatarImage src="/placeholder-avatar.jpg" alt="User avatar" />
            <AvatarFallback className="bg-sidebar-accent text-sidebar-foreground text-xs">
              CS
            </AvatarFallback>
          </Avatar>
          <div className="flex flex-1 flex-col overflow-hidden">
            <span className="truncate text-sm font-medium text-sidebar-foreground">
              @demo_user
            </span>
            <span className="truncate text-xs text-muted-foreground">
              Connected
            </span>
          </div>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="mt-1 w-full justify-start gap-2 text-muted-foreground hover:text-foreground"
        >
          <LogOut className="size-3.5" />
          Disconnect
        </Button>
      </div>
    </aside>
  )
}
