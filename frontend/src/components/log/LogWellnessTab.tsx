import { useEffect, useState } from "react"
import { fetchExistingWellness, saveWellness } from "@/lib/api"
import { todayLocal } from "@/lib/date"
import { CARD_CLASS } from "@/lib/styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { SliderField } from "@/components/log/SliderField"

type TriState = boolean | null

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

export function LogWellnessTab() {
  const [date, setDate] = useState(todayLocal())
  const [logScores, setLogScores] = useState(true)
  const [sleepQuality, setSleepQuality] = useState(5)
  const [stress, setStress] = useState(5)
  const [fatigue, setFatigue] = useState(5)
  const [muscleSoreness, setMuscleSoreness] = useState(5)
  const [proteinHit, setProteinHit] = useState<TriState>(null)
  const [socialMeal, setSocialMeal] = useState<TriState>(null)
  const [gassed, setGassed] = useState<TriState>(null)
  const [niggles, setNiggles] = useState("")
  const [dayNote, setDayNote] = useState("")
  const [existing, setExisting] = useState<{ hooper_index: number | null } | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [existingCheckError, setExistingCheckError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setExistingCheckError(null)
    fetchExistingWellness(date)
      .then((r) => {
        if (!cancelled) setExisting(r)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        console.error("Failed to check for an existing wellness entry:", err)
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
      const entry = await saveWellness({
        date,
        sleep_quality: logScores ? sleepQuality : null,
        stress: logScores ? stress : null,
        fatigue: logScores ? fatigue : null,
        muscle_soreness: logScores ? muscleSoreness : null,
        protein_hit: proteinHit,
        social_meal: socialMeal,
        gassed,
        niggles: niggles || null,
        day_note: dayNote || null,
      })
      const hooperIndex = entry.hooper_index as number | null
      setStatus({
        kind: "success",
        message:
          `Logged: ${date}` +
          (hooperIndex != null ? ` — hooper_index ${hooperIndex} (4=excellent, 40=terrible)` : ""),
      })
      setExisting(await fetchExistingWellness(date))
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Failed to save." })
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="wellness-date">Date</Label>
        <Input
          id="wellness-date"
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
          Already logged for {date} (hooper_index={existing.hooper_index ?? "—"}). Submitting again
          will overwrite it.
        </p>
      )}

      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={logScores}
            onChange={(e) => setLogScores(e.target.checked)}
            className="h-4 w-4 accent-[var(--band-blue)]"
          />
          Log the 4 wellness scores today
        </label>

        {logScores && (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">1 = best, 10 = worst</p>
            <SliderField label="Sleep quality" value={sleepQuality} onChange={setSleepQuality} min={1} max={10} />
            <SliderField label="Stress" value={stress} onChange={setStress} min={1} max={10} />
            <SliderField label="Fatigue" value={fatigue} onChange={setFatigue} min={1} max={10} />
            <SliderField
              label="Muscle soreness"
              value={muscleSoreness}
              onChange={setMuscleSoreness}
              min={1}
              max={10}
            />
          </div>
        )}

        <div className="grid grid-cols-3 gap-3">
          <TriStateSelect label="Hit 180g protein" value={proteinHit} onChange={setProteinHit} />
          <TriStateSelect label="Social meal" value={socialMeal} onChange={setSocialMeal} />
          <TriStateSelect label="Gassed today" value={gassed} onChange={setGassed} />
        </div>

        <div>
          <Label htmlFor="wellness-niggles">Niggles (free text)</Label>
          <Input
            id="wellness-niggles"
            value={niggles}
            onChange={(e) => setNiggles(e.target.value)}
            className="mt-1"
          />
        </div>
        <div>
          <Label htmlFor="wellness-day-note">Day note</Label>
          <Textarea
            id="wellness-day-note"
            value={dayNote}
            onChange={(e) => setDayNote(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Log wellness</Button>
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
