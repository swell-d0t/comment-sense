"use client"

export default function AuthCallbackPage() {
  // The real OAuth callback goes directly to the backend at REDIRECT_URI
  // (e.g. https://api.yourdomain.com/auth/callback), which then redirects
  // to the dashboard. This page is just a safety net if someone navigates
  // here manually.
  return null
}

