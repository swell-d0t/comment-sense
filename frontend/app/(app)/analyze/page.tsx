"use client"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { InstagramPostsTab } from "@/components/analyze/instagram-posts-tab"
import { PasteCommentsTab } from "@/components/analyze/paste-comments-tab"

export default function AnalyzePage() {
  return (
    <div className="flex flex-1 flex-col">
      {/* Header */}
      <header className="flex items-center justify-between border-b border-border px-6 py-4">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">
          Analyze
        </h1>
      </header>

      {/* Content */}
      <div className="flex flex-1 flex-col gap-6 px-6 py-6">
        <Tabs defaultValue="instagram" className="flex flex-1 flex-col">
          <TabsList className="w-fit">
            <TabsTrigger value="instagram">My Instagram Posts</TabsTrigger>
            <TabsTrigger value="paste">Paste Comments</TabsTrigger>
          </TabsList>

          <TabsContent value="instagram" className="mt-4">
            <InstagramPostsTab />
          </TabsContent>

          <TabsContent value="paste" className="mt-4">
            <PasteCommentsTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
