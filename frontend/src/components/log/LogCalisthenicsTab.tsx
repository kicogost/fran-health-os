import { useEffect, useState } from "react"
import {
  fetchExistingCalisthenics,
  fetchPrescribedExercises,
  saveCalisthenics,
} from "@/lib/api"
import { CARD_CLASS } from "@/lib/styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { SliderField } from "@/components/log/SliderField"

const SESSION_TYPES = [
  { value: "strength_a", label: "Strength A" },
  { value: "strength_b", label: "Strength B" },
]

function todayLocal(): string {
  return new Date().toISOString().slice(0, 10)
}

interface ExerciseInput {
  name: string
  sets: number
  reps: number
  addedWeight: number
}

export function LogCalisthenicsTab() {
  const [date, setDate] = useState(todayLocal())
  const [sessionType, setSessionType] = useState("strength_a")
  const [prescribed, setPrescribed] = useState<string[]>([])
  const [exerciseInputs, setExerciseInputs] = useState<ExerciseInput[]>([])
  const [rpe, setRpe] = useState(6)
  const [notes, setNotes] = useState("")
  const [existing, setExisting] = useState<{ session_rpe: number | null } | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchPrescribedExercises(sessionType).then((exercises) => {
      if (cancelled) return
      setPrescribed(exercises)
      setExerciseInputs(
        exercises.map((raw) => ({
          name: raw.split(":")[0].trim(),
          sets: 0,
          reps: 0,
          addedWeight: 0,
        })),
      )
    })
    fetchExistingCalisthenics(date, sessionType).then((r) => {
      if (!cancelled) setExisting(r)
    })
    return () => {
      cancelled = true
    }
  }, [date, sessionType])

  function updateExercise(index: number, field: keyof ExerciseInput, value: number) {
    setExerciseInputs((prev) =>
      prev.map((ex, i) => (i === index ? { ...ex, [field]: value } : ex)),
    )
  }

  async function handleSubmit() {
    setStatus(null)
    const exercises = exerciseInputs
      .filter((ex) => ex.sets > 0)
      .map((ex) => ({
        exercise: ex.name,
        sets: ex.sets,
        reps: ex.reps || null,
        added_weight_kg: ex.addedWeight || null,
        notes: null,
      }))
    try {
      const session = await saveCalisthenics({
        date,
        session_type: sessionType as "strength_a" | "strength_b",
        session_rpe: rpe,
        exercises: exercises.length > 0 ? exercises : null,
        notes: notes || null,
      })
      const suffix = exercises.length > 0 ? ` — ${exercises.length} exercises logged` : ""
      setStatus({
        kind: "success",
        message: `Logged: ${session.date} ${session.session_type}${suffix}`,
      })
      setExisting(await fetchExistingCalisthenics(date, sessionType))
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
          <Label htmlFor="cal-date">Date</Label>
          <Input
            id="cal-date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="mt-1"
          />
        </div>
      </div>

      {existing && (
        <p className="text-sm text-[var(--band-amber)] rounded-lg border border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10 px-3 py-2">
          Already logged for {date} ({sessionType}). Submitting again will overwrite it.
        </p>
      )}

      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        {prescribed.map((raw, i) => (
          <div key={raw}>
            <p className="text-xs text-muted-foreground mb-1.5">{raw}</p>
            <div className="grid grid-cols-3 gap-2">
              <Input
                type="number"
                min={0}
                max={20}
                placeholder="Sets"
                value={exerciseInputs[i]?.sets || ""}
                onChange={(e) => updateExercise(i, "sets", Number(e.target.value))}
              />
              <Input
                type="number"
                min={0}
                max={100}
                placeholder="Reps"
                value={exerciseInputs[i]?.reps || ""}
                onChange={(e) => updateExercise(i, "reps", Number(e.target.value))}
              />
              <Input
                type="number"
                min={0}
                max={100}
                step={0.5}
                placeholder="Added kg"
                value={exerciseInputs[i]?.addedWeight || ""}
                onChange={(e) => updateExercise(i, "addedWeight", Number(e.target.value))}
              />
            </div>
          </div>
        ))}

        <SliderField label="Session RPE" value={rpe} onChange={setRpe} min={1} max={10} />
        <div>
          <Label htmlFor="cal-notes">Notes</Label>
          <Textarea
            id="cal-notes"
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
    </div>
  )
}
