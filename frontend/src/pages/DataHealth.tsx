import { useEffect, useState } from "react"
import { AlertCircle, CheckCircle2, Clock, Database, Stethoscope } from "lucide-react"
import { ApiError, fetchDataHealth } from "@/lib/api"
import { CARD_CLASS, CARD_CLASS_FLAT } from "@/lib/styles"
import type { DataHealthPayload } from "@/types/dataHealth"

export function DataHealthPage() {
  const [data, setData] = useState<DataHealthPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetchDataHealth()
      .then((payload) => {
        if (!cancelled) setData(payload)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not reach the API.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <p className="text-muted-foreground p-8">Loading...</p>
  if (error)
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className={`${CARD_CLASS} p-5 border-[var(--band-red)]/30`}>
          <p className="text-sm text-foreground">{error}</p>
        </div>
      </div>
    )
  if (!data) return null

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <Stethoscope className="h-5 w-5 text-muted-foreground" strokeWidth={2} />
        <h1 className="text-2xl font-semibold text-foreground tracking-tight">Data Health</h1>
      </div>

      <div className={`${CARD_CLASS_FLAT} p-4`}>
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
          Freshness
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {data.freshness.map((f) => (
            <div key={f.field}>
              <p className="text-xs text-muted-foreground">{f.label}</p>
              <p className="text-lg font-semibold text-foreground flex items-center gap-1.5">
                {f.status === "no_data" ? (
                  <AlertCircle className="h-4 w-4 text-muted-foreground" strokeWidth={2} />
                ) : f.status === "today" ? (
                  <CheckCircle2 className="h-4 w-4 text-[var(--band-green)]" strokeWidth={2} />
                ) : (
                  <Clock className="h-4 w-4 text-[var(--band-amber)]" strokeWidth={2} />
                )}
                {f.status === "no_data" ? "no data" : f.status}
              </p>
              {f.last_date && <p className="text-xs text-muted-foreground">last: {f.last_date}</p>}
            </div>
          ))}
        </div>
      </div>

      <div className={`${CARD_CLASS_FLAT} p-4`}>
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
          Missing days (trailing {data.missing_days_window})
        </p>
        {data.missing_days.length === 0 ? (
          <p className="text-sm text-[var(--band-green)] flex items-center gap-1.5">
            <CheckCircle2 className="h-4 w-4" strokeWidth={2} />
            Every day in the trailing {data.missing_days_window} has at least one daily_metrics
            field.
          </p>
        ) : (
          <div className="rounded-lg border border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10 p-3">
            <p className="text-sm text-foreground">
              {data.missing_days.length} of {data.missing_days_window} days have no daily_metrics
              row at all:
            </p>
            <p className="text-xs text-muted-foreground mt-1">{data.missing_days.join(", ")}</p>
          </div>
        )}
      </div>

      <div className={`${CARD_CLASS_FLAT} p-4`}>
        <div className="flex items-center gap-2 mb-3">
          <Database className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Dedupe log
          </p>
        </div>
        {data.dedupe_log.length === 0 ? (
          <p className="text-sm text-muted-foreground">No cross-source merges recorded.</p>
        ) : (
          <div className="overflow-x-auto">
            <p className="text-sm text-muted-foreground mb-2">
              {data.dedupe_log.length} activities have absorbed at least one duplicate:
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="pb-2 pr-4 font-medium">Activity</th>
                  <th className="pb-2 pr-4 font-medium">Source</th>
                  <th className="pb-2 pr-4 font-medium">Date</th>
                  <th className="pb-2 pr-4 font-medium">Sport</th>
                  <th className="pb-2 font-medium">Merged from</th>
                </tr>
              </thead>
              <tbody>
                {data.dedupe_log.map((row) => (
                  <tr key={row.activity_id} className="border-b border-border/50 last:border-0">
                    <td className="py-2 pr-4 text-foreground font-mono text-xs">
                      {row.activity_id}
                    </td>
                    <td className="py-2 pr-4 text-foreground">{row.source}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{row.local_date}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{row.sport ?? "—"}</td>
                    <td className="py-2 text-muted-foreground text-xs">
                      {row.merged_from.map((m) => `${m.source}:${m.source_id}`).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className={`${CARD_CLASS_FLAT} p-4`}>
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
          Recent ingest runs
        </p>
        {data.ingest_runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No ingest runs recorded yet.</p>
        ) : (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border sticky top-0 bg-card">
                  <th className="pb-2 pr-4 font-medium">Source</th>
                  <th className="pb-2 pr-4 font-medium">Started</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 pr-4 font-medium">In / Upserted / Skipped</th>
                  <th className="pb-2 font-medium">Errors</th>
                </tr>
              </thead>
              <tbody>
                {data.ingest_runs.map((run) => (
                  <tr
                    key={run.id}
                    className={
                      run.status === "failed"
                        ? "bg-[var(--band-red)]/10 border-b border-border/50"
                        : "border-b border-border/50 last:border-0"
                    }
                  >
                    <td className="py-2 pr-4 text-foreground">{run.source}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{run.started_at}</td>
                    <td className="py-2 pr-4 text-foreground">{run.status}</td>
                    <td className="py-2 pr-4 text-muted-foreground tabular-nums">
                      {run.rows_in ?? "—"} / {run.rows_upserted ?? "—"} / {run.rows_skipped ?? "—"}
                    </td>
                    <td className="py-2 text-muted-foreground text-xs">
                      {run.errors ? run.errors.join("; ") : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
