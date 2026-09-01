import type { CompPrepPayload } from "@/types/compPrep"
import type { DataHealthPayload } from "@/types/dataHealth"
import type {
  BjjSessionRequest,
  CalisthenicsRequest,
  WaistRequest,
  WellnessRequest,
} from "@/types/log"
import type { TodayPayload } from "@/types/today"
import type { TrainingPayload } from "@/types/training"
import type { CorrelationResult, TrendsPayload } from "@/types/trends"

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

/** FastAPI route code in this project always raises `HTTPException(422,
 * detail=str(exc))` -- a plain string. But native Pydantic request-
 * validation errors (422s FastAPI raises itself, before any of our route
 * code runs -- e.g. a malformed request body) come back with `detail` as an
 * array of `{loc, msg, type}` objects instead. Passed straight through,
 * `Error`'s own message stringification renders that as the useless
 * "[object Object]". Detect the array shape and join each item's `msg`
 * into one readable string; anything else falls back to the original
 * string/statusText behavior unchanged.
 */
function formatErrorDetail(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String((item as { msg: unknown }).msg)
          : null,
      )
      .filter((m): m is string => m !== null)
    if (messages.length > 0) return messages.join("; ")
  }
  return undefined
}

async function handle<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, formatErrorDetail(body.detail) ?? response.statusText)
  }
  return response.json() as Promise<T>
}

function getJson<T>(path: string): Promise<T> {
  return fetch(`${API_BASE}${path}`).then((r) => handle<T>(r))
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r))
}

export function fetchToday(): Promise<TodayPayload> {
  return getJson<TodayPayload>("/today")
}

export function fetchTrends(windowDays: number): Promise<TrendsPayload> {
  return getJson<TrendsPayload>(`/trends?window_days=${windowDays}`)
}

export function fetchTraining(): Promise<TrainingPayload> {
  return getJson<TrainingPayload>("/training")
}

export function fetchCompPrep(): Promise<CompPrepPayload> {
  return getJson<CompPrepPayload>("/comp-prep")
}

export function fetchDataHealth(): Promise<DataHealthPayload> {
  return getJson<DataHealthPayload>("/data-health")
}

export function fetchCorrelations(): Promise<CorrelationResult[]> {
  return getJson<CorrelationResult[]>("/insights/correlations")
}

export function fetchPrescribedExercises(sessionType: string): Promise<string[]> {
  return getJson<string[]>(`/log/prescribed-exercises?session_type=${sessionType}`)
}

// --- Log: one GET (existing-entry check) + one POST (save) per log type ---

export function fetchExistingBjj(
  date: string,
  sessionType: string,
): Promise<{ duration_min: number; session_rpe: number; computed_load: number } | null> {
  return getJson(`/log/bjj?date=${date}&session_type=${sessionType}`)
}

export function saveBjj(req: BjjSessionRequest): Promise<Record<string, unknown>> {
  return postJson("/log/bjj", req)
}

export function fetchExistingWellness(
  date: string,
): Promise<{ hooper_index: number | null } | null> {
  return getJson(`/log/wellness?date=${date}`)
}

export function saveWellness(req: WellnessRequest): Promise<Record<string, unknown>> {
  return postJson("/log/wellness", req)
}

export function fetchExistingWaist(date: string): Promise<{ value_cm: number } | null> {
  return getJson(`/log/waist?date=${date}`)
}

export function saveWaist(req: WaistRequest): Promise<Record<string, unknown>> {
  return postJson("/log/waist", req)
}

export function fetchExistingCalisthenics(
  date: string,
  sessionType: string,
): Promise<{ session_rpe: number | null } | null> {
  return getJson(`/log/calisthenics?date=${date}&session_type=${sessionType}`)
}

export function saveCalisthenics(req: CalisthenicsRequest): Promise<Record<string, unknown>> {
  return postJson("/log/calisthenics", req)
}
