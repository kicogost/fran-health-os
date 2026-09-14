import { useEffect, useState } from "react"
import { fetchExistingIllness, saveIllness } from "@/lib/api"
import { todayLocal } from "@/lib/date"
import { CARD_CLASS } from "@/lib/styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { SliderField } from "@/components/log/SliderField"

type TriState = boolean | null

// Same tri-state Skip/Yes/No pattern as LogWellnessTab's TriStateSelect --
// a checkbox can't represent "not mentioned today" (design principle 6),
// which every symptom here genuinely needs (Francisco very often logs a
// couple of symptoms and leaves the rest unmentioned, not explicitly "no").
function TriStateSelect({
  label,
  value,
  onChange,
}: {
  label: string
  value: TriState
  onChange: (v: TriState) => void
}) {
  const stringValue = value === null ? "skip" : value ? "yes" : "no"
  return (
    <div>
      <Label>{label}</Label>
      <Select
        value={stringValue}
        onValueChange={(v) => onChange(v === "skip" ? null : v === "yes")}
      >
        <SelectTrigger className="w-full mt-1">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="skip">Skip</SelectItem>
          <SelectItem value="yes">Yes</SelectItem>
          <SelectItem value="no">No</SelectItem>
        </SelectContent>
      </Select>
    </div>
  )
}

/** Illness log — one row per DATE (migration 0006), not per "episode": a run
 * of consecutive dated entries reads as one episode after the fact, no
 * separate start/end field needed. Every field is optional; whatever isn't
 * touched stays unset/null, never invented. Built so illness can eventually
 * be correlated against HRV/RHR/sleep/training-load once enough real
 * episodes accumulate (metrics/correlations.py's MIN_N=30 gate, not wired
 * in yet).
 */
export function LogIllnessTab() {
  const [date, setDate] = useState(todayLocal())
  const [logSeverity, setLogSeverity] = useState(false)
  const [severity, setSeverity] = useState(5)
  const [soreThroat, setSoreThroat] = useState<TriState>(null)
  const [fever, setFever] = useState<TriState>(null)
  const [temperatureC, setTemperatureC] = useState("")
  const [congestion, setCongestion] = useState<TriState>(null)
  const [cough, setCough] = useState<TriState>(null)
  const [bodyAches, setBodyAches] = useState<TriState>(null)
  const [fatigueWeakness, setFatigueWeakness] = useState<TriState>(null)
  const [headache, setHeadache] = useState<TriState>(null)
  const [likelyCause, setLikelyCause] = useState("")
  const [notes, setNotes] = useState("")
  const [existing, setExisting] = useState<{ severity: number | null } | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [existingCheckError, setExistingCheckError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setExistingCheckError(null)
    fetchExistingIllness(date)
      .then((r) => {
        if (!cancelled) setExisting(r)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        console.error("Failed to check for an existing illness entry:", err)
        setExisting(null)
        setExistingCheckError(err instanceof Error ? err.message : "Could not reach the API.")
      })
    return () => {
      cancelled = true
    }
  }, [date])

  async function handleSubmit() {
    setStatus(null)
    try {
      const entry = await saveIllness({
        date,
        severity: logSeverity ? severity : null,
        sore_throat: soreThroat,
        fever,
        temperature_c: temperatureC === "" ? null : Number(temperatureC),
        congestion,
        cough,
        body_aches: bodyAches,
        fatigue_weakness: fatigueWeakness,
        headache,
        likely_cause: likelyCause || null,
        notes: notes || null,
      })
      const loggedSeverity = entry.severity as number | null
      setStatus({
        kind: "success",
        message: `Logged: ${date}` + (loggedSeverity != null ? ` — severity ${loggedSeverity}/10` : ""),
      })
      setExisting(await fetchExistingIllness(date))
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Failed to save." })
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="illness-date">Date</Label>
        <Input
          id="illness-date"
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="mt-1 max-w-xs"
        />
      </div>

      {existingCheckError && (
        <p className="text-xs text-muted-foreground">
          Couldn&apos;t check for an existing entry: {existingCheckError}
        </p>
      )}

      {existing && (
        <p className="text-sm text-[var(--band-amber)] rounded-lg border border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10 px-3 py-2">
          Already logged for {date} (severity={existing.severity ?? "—"}). Submitting again will
          overwrite it.
        </p>
      )}

      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={logSeverity}
            onChange={(e) => setLogSeverity(e.target.checked)}
            className="h-4 w-4 accent-[var(--band-blue)]"
          />
          Rate overall severity today
        </label>

        {logSeverity && (
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              1 = barely noticeable, 10 = severe/incapacitated
            </p>
            <SliderField label="Severity" value={severity} onChange={setSeverity} min={1} max={10} />
          </div>
        )}

        <div>
          <p className="text-xs text-muted-foreground mb-2">Symptoms — skip any not mentioned</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <TriStateSelect label="Sore throat" value={soreThroat} onChange={setSoreThroat} />
            <TriStateSelect label="Feels feverish" value={fever} onChange={setFever} />
            <TriStateSelect label="Congestion" value={congestion} onChange={setCongestion} />
            <TriStateSelect label="Cough" value={cough} onChange={setCough} />
            <TriStateSelect label="Body aches" value={bodyAches} onChange={setBodyAches} />
            <TriStateSelect
              label="Fatigue / weakness"
              value={fatigueWeakness}
              onChange={setFatigueWeakness}
            />
            <TriStateSelect label="Headache" value={headache} onChange={setHeadache} />
          </div>
        </div>

        <div>
          <Label htmlFor="illness-temperature">Measured temperature (°C, blank if not taken)</Label>
          <Input
            id="illness-temperature"
            type="number"
            step={0.1}
            value={temperatureC}
            onChange={(e) => setTemperatureC(e.target.value)}
            className="mt-1 max-w-xs"
            placeholder="not measured"
          />
          <p className="text-xs text-muted-foreground mt-1">
            &ldquo;Feels feverish&rdquo; above is self-assessed — this is only for an actual
            thermometer reading.
          </p>
        </div>

        <div>
          <Label htmlFor="illness-likely-cause">Likely cause (your own guess)</Label>
          <Input
            id="illness-likely-cause"
            value={likelyCause}
            onChange={(e) => setLikelyCause(e.target.value)}
            className="mt-1"
            placeholder="e.g. viral, allergies, unknown"
          />
        </div>
        <div>
          <Label htmlFor="illness-notes">Notes</Label>
          <Textarea
            id="illness-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Log illness</Button>
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
    </div>
  )
}
