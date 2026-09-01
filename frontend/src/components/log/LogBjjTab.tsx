import { useEffect, useState } from "react"
import { fetchExistingBjj, saveBjj } from "@/lib/api"
import { todayLocal } from "@/lib/date"
import { CARD_CLASS } from "@/lib/styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { SliderField } from "@/components/log/SliderField"

const SESSION_TYPES = [
  { value: "class", label: "Class" },
  { value: "open_mat", label: "Open mat" },
  { value: "gi_drilling", label: "Gi drilling" },
]
const SESSION_FEELINGS = ["dizzy", "gassed", "tired", "okay"] // worst to best, matches core/models.py

export function LogBjjTab() {
  const [date, setDate] = useState(todayLocal())
  const [sessionType, setSessionType] = useState("class")
  const [duration, setDuration] = useState(90)
  const [rpe, setRpe] = useState(7)
  const [roundsRolled, setRoundsRolled] = useState(6)
  const [roundsGassed, setRoundsGassed] = useState(0)
  const [feeling, setFeeling] = useState("tired")
  const [niggles, setNiggles] = useState("")
  const [notes, setNotes] = useState("")
  const [existing, setExisting] = useState<{
    duration_min: number
    session_rpe: number
    computed_load: number
  } | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [dizzyWarning, setDizzyWarning] = useState(false)
  const [existingCheckError, setExistingCheckError] = useState<string | null>(null)

  const rolling = sessionType === "class" || sessionType === "open_mat"

  useEffect(() => {
    let cancelled = false
    setExistingCheckError(null)
    fetchExistingBjj(date, sessionType)
      .then((r) => {
        if (!cancelled) setExisting(r)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        console.error("Failed to check for an existing BJJ entry:", err)
        setExisting(null)
        setExistingCheckError(err instanceof Error ? err.message : "Could not reach the API.")
      })
    return () => {
      cancelled = true
    }
  }, [date, sessionType])

  async function handleSubmit() {
    setStatus(null)
    setDizzyWarning(false)
    try {
      const session = await saveBjj({
        date,
        session_type: sessionType as "class" | "open_mat" | "gi_drilling",
        duration_min: duration,
        session_rpe: rpe,
        rounds_rolled: rolling ? roundsRolled : null,
        rounds_gassed: rolling ? roundsGassed : null,
        session_feeling: rolling ? (feeling as "dizzy" | "gassed" | "tired" | "okay") : null,
        niggles: niggles || null,
        notes: notes || null,
      })
      setStatus({
        kind: "success",
        message: `Logged: ${date} ${sessionType} — load ${Number(session.computed_load).toFixed(0)}`,
      })
      setDizzyWarning(rolling && feeling === "dizzy")
      setExisting(await fetchExistingBjj(date, sessionType))
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Failed to save." })
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label>Session type</Label>
          <Select value={sessionType} onValueChange={setSessionType}>
            <SelectTrigger className="w-full mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SESSION_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label htmlFor="bjj-date">Date</Label>
          <Input
            id="bjj-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="mt-1"
          />
        </div>
      </div>

      {existingCheckError && (
        <p className="text-xs text-muted-foreground">
          Couldn&apos;t check for an existing entry: {existingCheckError}
        </p>
      )}

      {existing && (
        <p className="text-sm text-[var(--band-amber)] rounded-lg border border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10 px-3 py-2">
          Already logged for {date}: {existing.duration_min}min @ RPE {existing.session_rpe} (load{" "}
          {existing.computed_load.toFixed(0)}). Submitting again will overwrite it.
        </p>
      )}

      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        <div>
          <Label htmlFor="bjj-duration">Duration (min)</Label>
          <Input
            id="bjj-duration"
            type="number"
            min={1}
            max={600}
            value={duration}
            onChange={(e) => setDuration(Number(e.target.value))}
            className="mt-1"
          />
        </div>
        <SliderField label="Session RPE" value={rpe} onChange={setRpe} min={1} max={10} />
        {rolling && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="bjj-rounds">Rounds rolled</Label>
                <Input
                  id="bjj-rounds"
                  type="number"
                  min={0}
                  max={30}
                  value={roundsRolled}
                  onChange={(e) => setRoundsRolled(Number(e.target.value))}
                  className="mt-1"
                />
              </div>
              <div>
                <Label htmlFor="bjj-gassed">Rounds gassed on</Label>
                <Input
                  id="bjj-gassed"
                  type="number"
                  min={0}
                  max={roundsRolled}
                  value={roundsGassed}
                  onChange={(e) => setRoundsGassed(Number(e.target.value))}
                  className="mt-1"
                />
              </div>
            </div>
            <div>
              <Label>Feeling at the end</Label>
              <Select value={feeling} onValueChange={setFeeling}>
                <SelectTrigger className="w-full mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SESSION_FEELINGS.map((f) => (
                    <SelectItem key={f} value={f}>
                      {f}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </>
        )}
        <div>
          <Label htmlFor="bjj-niggles">Niggles (free text)</Label>
          <Input
            id="bjj-niggles"
            value={niggles}
            onChange={(e) => setNiggles(e.target.value)}
            className="mt-1"
          />
        </div>
        <div>
          <Label htmlFor="bjj-notes">Notes</Label>
          <Textarea
            id="bjj-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Log session</Button>
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
      {dizzyWarning && (
        <p className="text-sm px-3 py-2 rounded-lg border text-[var(--band-amber)] border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10">
          Logged &apos;dizzy&apos; — that&apos;s more than normal hard-training fatigue.
        </p>
      )}
    </div>
  )
}
