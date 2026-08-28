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
import type { TrendsPayload } from "@/types/trends"

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

async function handle<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.detail ?? response.statusText)
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
