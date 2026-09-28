import { useState } from "react"
import { RefreshCw } from "lucide-react"
import { triggerSync } from "@/lib/api"

type Status = { kind: "idle" } | { kind: "syncing" } | { kind: "error"; message: string }

/** Manual "sync now" button, always visible in the sidebar footer.
 *
 * Real trigger (2026-09-17): Francisco opens the app most mornings and sees
 * yesterday's data, because the scheduled launchd syncs (07:00/09:30
 * morning, 21:30 quiet sync) haven't always run yet by the time he checks.
 * Every page here already fetches fresh data from the API on load -- there
 * is no client-side cache to "refresh" -- so what was actually missing was
 * a way to make the DATABASE itself pull new data on demand, not just
 * re-read the same stale rows. Clicking this calls `POST /api/sync` (real
 * Garmin/Health Auto Export/RENPHO calls, can take several seconds), then
 * reloads the page once it resolves so whichever page is open re-fetches
 * against the now-current database -- simplest robust option given no page
 * shares state with another (no global store to invalidate instead).
 */
export function SyncButton() {
  const [status, setStatus] = useState<Status>({ kind: "idle" })

  async function handleClick() {
    setStatus({ kind: "syncing" })
    try {
      const result = await triggerSync()
      if (result.status === "partial_failure") {
        const failed = Object.entries(result.sources)
          .filter(([, ok]) => !ok)
          .map(([name]) => name.replace(/_/g, " "))
          .join(", ")
        setStatus({ kind: "error", message: `Synced, but ${failed} failed -- check logs.` })
        return
      }
      // A full reload (not a re-fetch call) so every page's own data-loading
      // effect re-runs against the now-current database -- there's no
      // shared/global data store here to invalidate more surgically.
      window.location.reload()
    } catch (err) {
      setStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Sync failed -- check the API is running.",
      })
    }
  }

  const syncing = status.kind === "syncing"

  return (
    <div className="px-3 pb-4">
      <button
        onClick={handleClick}
        disabled={syncing}
        className="flex w-full items-center justify-center gap-2 rounded-full border border-border px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground hover:bg-accent/50 disabled:opacity-60 disabled:cursor-not-allowed"
      >
        <RefreshCw className={`size-3.5 ${syncing ? "animate-spin motion-reduce:animate-none" : ""}`} />
        {syncing ? "Syncing…" : "Sync now"}
      </button>
      {status.kind === "error" && (
        <p className="mt-2 text-xs text-[var(--band-red)] px-1">{status.message}</p>
      )}
    </div>
  )
}
