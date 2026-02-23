const API_URL = process.env.NEXT_PUBLIC_API_URL

if (!API_URL) {
  throw new Error("NEXT_PUBLIC_API_URL is not set. Please configure it in .env.local.")
}

// ── Types ───────────────────────────────────────────────────────────────────

export interface CommentAnalysis {
  text: string
  sentiment: "positive" | "neutral" | "negative"
  confidence: number
  flags: string[]
}

export interface AnalysisResult {
  id: string
  label: string
  totalComments: number
  positive: number
  neutral: number
  negative: number
  averageConfidence: number
  overallSentiment: "positive" | "neutral" | "negative"
  mostPositive: CommentAnalysis | null
  mostNegative: CommentAnalysis | null
  comments: CommentAnalysis[]
  createdAt: string
}

export interface InstagramPost {
  id: string
  thumbnailUrl: string
  caption: string
  commentCount: number
  timestamp: string
  permalink: string
}

export interface PostComment {
  id: string
  text: string
  username: string
  timestamp: string
}

// ── Error Types ─────────────────────────────────────────────────────────────

export class ApiError extends Error {
  code: number
  detail: string

  constructor(code: number, detail: string) {
    super(`API Error ${code}: ${detail}`)
    this.name = "ApiError"
    this.code = code
    this.detail = detail
  }
}

export class ValidationError extends ApiError {
  constructor(detail: string) {
    super(422, detail)
    this.name = "ValidationError"
  }
}

export class BadRequestError extends ApiError {
  constructor(detail: string) {
    super(400, detail)
    this.name = "BadRequestError"
  }
}

export class ServiceUnavailableError extends ApiError {
  constructor(detail: string) {
    super(503, detail)
    this.name = "ServiceUnavailableError"
  }
}

export class InternalServerError extends ApiError {
  constructor(detail: string) {
    super(500, detail)
    this.name = "InternalServerError"
  }
}

// ── Helper ──────────────────────────────────────────────────────────────────

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = "An unexpected error occurred"
    try {
      const body = await response.json()
      detail = body.detail || body.message || detail
    } catch {
      // Failed to parse response body
    }

    switch (response.status) {
      case 400:
        throw new BadRequestError(detail)
      case 422:
        throw new ValidationError(detail)
      case 503:
        throw new ServiceUnavailableError(detail)
      case 500:
      default:
        throw new InternalServerError(detail)
    }
  }

  return response.json() as Promise<T>
}

// ── API Functions ───────────────────────────────────────────────────────────

/**
 * Analyze raw pasted comments text.
 */
export async function analyzeComments(
  label: string,
  rawText: string
): Promise<AnalysisResult> {
  const response = await fetch(`${API_URL}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ label, raw_text: rawText }),
  })

  return handleResponse<AnalysisResult>(response)
}

/**
 * Analyze comments for multiple Instagram posts by ID.
 */
export async function analyzeBatch(
  posts: { postId: string; label?: string }[]
): Promise<AnalysisResult[]> {
  const response = await fetch(`${API_URL}/api/analyze/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ posts }),
  })

  return handleResponse<AnalysisResult[]>(response)
}

/**
 * Fetch the authenticated user's Instagram posts.
 */
export async function fetchMyPosts(): Promise<InstagramPost[]> {
  const response = await fetch(`${API_URL}/api/instagram/posts`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
  })

  return handleResponse<InstagramPost[]>(response)
}

/**
 * Fetch comments for a specific Instagram post.
 */
export async function fetchPostComments(
  postId: string
): Promise<PostComment[]> {
  const response = await fetch(
    `${API_URL}/api/instagram/posts/${postId}/comments`,
    {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
    }
  )

  return handleResponse<PostComment[]>(response)
}

// ── History ───────────────────────────────────────────────────────────────────

export interface AnalysisSummary {
  id: string
  label: string
  totalComments: number
  overallSentiment: "positive" | "neutral" | "negative"
  createdAt: string
}

export async function fetchHistory(): Promise<AnalysisSummary[]> {
  const response = await fetch(`${API_URL}/api/history`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
  })

  return handleResponse<AnalysisSummary[]>(response)
}

export async function fetchAnalysisDetail(id: string): Promise<AnalysisResult> {
  const response = await fetch(`${API_URL}/api/history/${id}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
  })

  return handleResponse<AnalysisResult>(response)
}

