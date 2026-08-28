import type { TodayPayload } from "@/types/today"

// Relative path -- the Vite dev server proxies /api to the FastAPI backend
// (vite.config.ts), and in production FastAPI serves this same built bundle
// itself, so /api/... resolves correctly either way with no base-URL
// configuration needed. Local-only either way (design principle 1).
const API_BASE = "/api"

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.detail ?? response.statusText)
  }
  return response.json() as Promise<T>
}

export function fetchToday(): Promise<TodayPayload> {
  return getJson<TodayPayload>("/today")
}
