import { useEffect, useState } from "react"
import { fetchExistingWaist, saveWaist } from "@/lib/api"
import { todayLocal } from "@/lib/date"
import { CARD_CLASS } from "@/lib/styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export function LogWaistTab() {
  const [date, setDate] = useState(todayLocal())
  const [valueCm, setValueCm] = useState(86.0)
  const [notes, setNotes] = useState("")
  const [existing, setExisting] = useState<{ value_cm: number } | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [existingCheckError, setExistingCheckError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setExistingCheckError(null)
    fetchExistingWaist(date)
      .then((r) => {
        if (!cancelled) setExisting(r)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        console.error("Failed to check for an existing waist entry:", err)
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
      const measurement = await saveWaist({ date, value_cm: valueCm, notes: notes || null })
      setStatus({
        kind: "success",
        message: `Logged: ${date} waist = ${measurement.value_cm} cm`,
      })
      setExisting(await fetchExistingWaist(date))
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Failed to save." })
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="waist-date">Date</Label>
        <Input
          id="waist-date"
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
          Already logged for {date} ({existing.value_cm} cm). Submitting again will overwrite it.
        </p>
      )}

      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        <div>
          <Label htmlFor="waist-value">Waist (cm)</Label>
          <Input
            id="waist-value"
            type="number"
            min={40}
            max={200}
            step={0.1}
            value={valueCm}
            onChange={(e) => setValueCm(Number(e.target.value))}
            className="mt-1 max-w-xs"
          />
        </div>
        <div>
          <Label htmlFor="waist-notes">Notes</Label>
          <Input
            id="waist-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Log measurement</Button>
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
