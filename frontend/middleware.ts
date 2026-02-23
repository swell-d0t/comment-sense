import { NextResponse } from "next/server"
import type { NextRequest } from "next/server"

export function middleware(request: NextRequest) {
  try {
    const session = request.cookies.get("session")

    if (!session || !session.value || session.value.length < 16) {
      const loginUrl = new URL("/login", request.url)
      return NextResponse.redirect(loginUrl)
    }

    return NextResponse.next()
  } catch (error) {
    console.error("Error in auth middleware", error)
    const loginUrl = new URL("/login", request.url)
    return NextResponse.redirect(loginUrl)
  }
}

export const config = {
  matcher: ["/dashboard/:path*", "/analyze/:path*"],
}

