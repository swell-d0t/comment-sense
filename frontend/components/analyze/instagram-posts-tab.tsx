"use client"

import { useEffect, useState } from "react"
import { Calendar, MessageSquare } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { PostDetailSheet } from "@/components/analyze/post-detail-sheet"
import { fetchMyPosts, type InstagramPost } from "@/lib/api"
import { LoadingSpinner } from "@/components/loading-spinner"
import { ErrorBanner } from "@/components/error-banner"

export function InstagramPostsTab() {
  const [selectedPost, setSelectedPost] = useState<InstagramPost | null>(null)
  const [posts, setPosts] = useState<InstagramPost[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true

    const load = async () => {
      try {
        setLoading(true)
        setError(null)
        const data = await fetchMyPosts()
        if (!isMounted) return
        setPosts(data)
      } catch (err) {
        if (!isMounted) return
        if (err instanceof Error) {
          setError(err.message)
        } else {
          setError("Failed to load posts. Please try again.")
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

  return (
    <>
      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-4">
          <LoadingSpinner size="sm" className="border-primary-foreground/30 border-t-primary-foreground" />
          Syncing your Instagram posts...
        </div>
      )}

      {error && (
        <ErrorBanner
          message={error}
          className="mb-4"
          onDismiss={() => setError(null)}
        />
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {posts.map((post) => (
          <Card
            key={post.id}
            className="cursor-pointer py-0 overflow-hidden transition-colors hover:border-foreground/20"
            onClick={() => setSelectedPost(post)}
          >
            {/* Thumbnail placeholder */}
            <div className="aspect-square bg-muted flex items-center justify-center">
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <div className="size-10 rounded-lg bg-border/50 flex items-center justify-center">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <rect x="2" y="2" width="20" height="20" rx="5" />
                    <circle cx="12" cy="12" r="5" />
                    <circle cx="18" cy="6" r="1.5" />
                  </svg>
                </div>
              </div>
            </div>

            <CardContent className="flex flex-col gap-2 p-4">
              <p className="line-clamp-2 text-sm text-foreground leading-relaxed">
                {post.caption}
              </p>
              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                <span className="flex items-center gap-1 font-mono">
                  <MessageSquare className="size-3" />
                  {post.commentCount}
                </span>
                <span className="flex items-center gap-1 font-mono">
                  <Calendar className="size-3" />
                  {post.date}
                </span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <PostDetailSheet
        post={selectedPost}
        open={!!selectedPost}
        onOpenChange={(open) => !open && setSelectedPost(null)}
      />
    </>
  )
}
