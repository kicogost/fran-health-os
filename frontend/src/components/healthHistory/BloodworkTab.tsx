import { useEffect, useState } from "react"
import { FlaskConical } from "lucide-react"
import { fetchBloodwork, saveBloodwork } from "@/lib/api"
import { todayLocal } from "@/lib/date"
import { CARD_CLASS, CARD_CLASS_FLAT } from "@/lib/styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import type { BloodworkRow } from "@/types/healthHistory"

/** Groups already-date-sorted rows into (date, rows) pairs, preserving the
 * API's own ordering (date DESC, test_name ASC) -- Map preserves first-
 * insertion order, so no separate sort is needed here.
 */
function groupByDate(rows: BloodworkRow[]): [string, BloodworkRow[]][] {
  const groups = new Map<string, BloodworkRow[]>()
  for (const row of rows) {
    const existing = groups.get(row.date)
    if (existing) existing.push(row)
    else groups.set(row.date, [row])
  }
  return Array.from(groups.entries())
}

function formatRange(row: BloodworkRow): string {
  if (row.reference_range_low == null && row.reference_range_high == null) return "—"
  return `${row.reference_range_low ?? "—"} – ${row.reference_range_high ?? "—"}`
}

/** Bloodwork -- a real "long/tall" table server-side (one row per test value
 * per draw date, core/migrations/0009_health_history.sql), grouped back
 * into per-draw-date blocks here so a full panel reads as one block, not N
 * disconnected rows. No natural key: every submit is a fresh INSERT, never
 * an overwrite -- there's nothing to warn about.
 */
export function BloodworkTab() {
  const [date, setDate] = useState(todayLocal())
  const [testName, setTestName] = useState("")
  const [value, setValue] = useState("")
  const [unit, setUnit] = useState("")
  const [rangeLow, setRangeLow] = useState("")
  const [rangeHigh, setRangeHigh] = useState("")
  const [notes, setNotes] = useState("")
  const [results, setResults] = useState<BloodworkRow[] | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function refresh() {
    fetchBloodwork()
      .then((rows) => {
        setResults(rows)
        setLoadError(null)
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : "Could not reach the API.")
      })
  }

  useEffect(() => {
    refresh()
  }, [])

  async function handleSubmit() {
    setStatus(null)
    if (!testName.trim() || value === "") {
      setStatus({ kind: "error", message: "Test name and value are both required." })
      return
    }
    try {
      await saveBloodwork({
        date,
        test_name: testName.trim(),
        value: Number(value),
        unit: unit.trim() || null,
        reference_range_low: rangeLow === "" ? null : Number(rangeLow),
        reference_range_high: rangeHigh === "" ? null : Number(rangeHigh),
        notes: notes.trim() || null,
      })
      setStatus({
        kind: "success",
        message: `Logged: ${date} ${testName} = ${value}${unit ? ` ${unit}` : ""}`,
      })
      setTestName("")
      setValue("")
      setUnit("")
      setRangeLow("")
      setRangeHigh("")
      setNotes("")
      refresh()
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Failed to save." })
    }
  }

  const grouped = results ? groupByDate(results) : []

  return (
    <div className="space-y-4">
      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="bloodwork-date">Draw date</Label>
            <Input
              id="bloodwork-date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="bloodwork-test-name">Test name</Label>
            <Input
              id="bloodwork-test-name"
              value={testName}
              onChange={(e) => setTestName(e.target.value)}
              className="mt-1"
              placeholder="e.g. ferritin"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="bloodwork-value">Value</Label>
            <Input
              id="bloodwork-value"
              type="number"
              step="any"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="bloodwork-unit">Unit</Label>
            <Input
              id="bloodwork-unit"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
              className="mt-1"
              placeholder="e.g. ng/mL"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="bloodwork-range-low">Reference range low</Label>
            <Input
              id="bloodwork-range-low"
              type="number"
              step="any"
              value={rangeLow}
              onChange={(e) => setRangeLow(e.target.value)}
              className="mt-1"
              placeholder="optional"
            />
          </div>
          <div>
            <Label htmlFor="bloodwork-range-high">Reference range high</Label>
            <Input
              id="bloodwork-range-high"
              type="number"
              step="any"
              value={rangeHigh}
              onChange={(e) => setRangeHigh(e.target.value)}
              className="mt-1"
              placeholder="optional"
            />
          </div>
        </div>
        <div>
          <Label htmlFor="bloodwork-notes">Notes</Label>
          <Textarea
            id="bloodwork-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Add result</Button>
      </div>

      {status && (
        <p
          className={`text-sm px-3 py-2 rounded-lg border ${
            status.kind === "success"
              ? "text-[var(--band-green)] border-[var(--band-green)]/30 bg-[var(--band-green)]/10"
              : "text-[var(--band-red)] border-[var(--band-red)]/30 bg-[var(--band-red)]/10"
          }`}
        >
          {status.message}
        </p>
      )}

      <div className={`${CARD_CLASS_FLAT} p-4`}>
        <div className="flex items-center gap-2 mb-3">
          <FlaskConical className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            History, grouped by draw date
          </p>
        </div>
        {loadError && (
          <p className="text-sm text-muted-foreground">Couldn&apos;t load history: {loadError}</p>
        )}
        {!loadError && grouped.length === 0 && (
          <p className="text-sm text-muted-foreground">No bloodwork logged yet.</p>
        )}
        <div className="space-y-4">
          {grouped.map(([groupDate, rows]) => (
            <div key={groupDate}>
              <p className="text-sm font-medium text-foreground mb-1">{groupDate}</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground border-b border-border">
                      <th className="pb-2 pr-4 font-medium">Test</th>
                      <th className="pb-2 pr-4 font-medium">Value</th>
                      <th className="pb-2 pr-4 font-medium">Reference range</th>
                      <th className="pb-2 font-medium">Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr
                        key={r.id}
                        className="border-b border-border/50 last:border-0 even:bg-accent/20"
                      >
                        <td className="py-2 pr-4 text-foreground">{r.test_name}</td>
                        <td className="py-2 pr-4 text-foreground tabular-nums">
                          {r.value}
                          {r.unit ? ` ${r.unit}` : ""}
                        </td>
                        <td className="py-2 pr-4 text-muted-foreground tabular-nums">
                          {formatRange(r)}
                        </td>
                        <td className="py-2 text-muted-foreground text-xs">{r.notes ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
