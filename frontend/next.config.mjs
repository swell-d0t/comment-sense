/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL

    if (!backendUrl) {
      console.warn(
        "NEXT_PUBLIC_API_URL is not set. API requests to /api/* will fail at runtime."
      )
      return []
    }

    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ]
  },
}

export default nextConfig
