"use client"

import { useState } from "react"
import { Calendar, MessageSquare } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { PostDetailSheet } from "@/components/analyze/post-detail-sheet"

interface InstagramPost {
  id: string
  thumbnailUrl: string
  caption: string
  commentCount: number
  date: string
}

const mockPosts: InstagramPost[] = [
  {
    id: "1",
    thumbnailUrl: "",
    caption: "Just launched our newest product line! Check it out via the link in bio. We've been working on this for months and can't wait for you to see it.",
    commentCount: 342,
    date: "Feb 20, 2026",
  },
  {
    id: "2",
    thumbnailUrl: "",
    caption: "Behind the scenes at our latest photoshoot. The team really brought their A-game today!",
    commentCount: 189,
    date: "Feb 18, 2026",
  },
  {
    id: "3",
    thumbnailUrl: "",
    caption: "Hear what our customers have to say about their experience. Real stories, real people.",
    commentCount: 97,
    date: "Feb 15, 2026",
  },
  {
    id: "4",
    thumbnailUrl: "",
    caption: "Important update: We're adjusting our pricing to better reflect the value we provide. Details below.",
    commentCount: 521,
    date: "Feb 12, 2026",
  },
  {
    id: "5",
    thumbnailUrl: "",
    caption: "Happy Friday from the whole team! Here's to another great week in the books.",
    commentCount: 64,
    date: "Feb 10, 2026",
  },
  {
    id: "6",
    thumbnailUrl: "",
    caption: "New tutorial: How to get the most out of our platform in just 5 minutes a day.",
    commentCount: 231,
    date: "Feb 7, 2026",
  },
]

export function InstagramPostsTab() {
  const [selectedPost, setSelectedPost] = useState<InstagramPost | null>(null)

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {mockPosts.map((post) => (
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
