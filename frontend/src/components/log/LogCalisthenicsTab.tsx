import { useEffect, useState } from "react"
import { Plus, X } from "lucide-react"
import {
  fetchExistingCalisthenics,
  fetchPrescribedExercises,
  saveCalisthenics,
} from "@/lib/api"
import { todayLocal } from "@/lib/date"
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

interface ExerciseInput {
  name: string
  sets: number
  reps: number
  addedWeight: number
}

// Beyond the prescribed list -- real gap found 2026-08-28 (Francisco's
// holiday-week substitution, e.g. push-ups/abs instead of the comp-prep
// exercises): CalisthenicsSession.exercises was always fully flexible at
// the model layer, but this form only ever rendered the prescribed rows,
// so a substituted exercise had no way in besides the free-text notes
// field. `id` is a client-only key (crypto.randomUUID -- stable across
// re-renders regardless of name edits, unlike using the name itself).
interface CustomExerciseInput extends ExerciseInput {
  id: string
}

function newCustomExercise(): CustomExerciseInput {
  return { id: crypto.randomUUID(), name: "", sets: 0, reps: 0, addedWeight: 0 }
}

export function LogCalisthenicsTab() {
  const [date, setDate] = useState(todayLocal())
  const [sessionType, setSessionType] = useState("strength_a")
  const [prescribed, setPrescribed] = useState<string[]>([])
  const [exerciseInputs, setExerciseInputs] = useState<ExerciseInput[]>([])
  const [customExercises, setCustomExercises] = useState<CustomExerciseInput[]>([])
  const [rpe, setRpe] = useState(6)
  const [notes, setNotes] = useState("")
  const [existing, setExisting] = useState<{ session_rpe: number | null } | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [existingCheckError, setExistingCheckError] = useState<string | null>(null)

  // Resets the prescribed-exercise rows and any in-progress custom rows.
  // Deliberately keyed on `sessionType` ONLY, not `date` -- fetching the
  // prescribed list only ever depends on the session type. Real bug fixed
  // 2026-08-31: this used to also run on every `date` change, which
  // unconditionally wiped `exerciseInputs`/`customExercises` back to
  // blank/zero -- so backdating a forgotten entry (changing just the date
  // field) silently discarded whatever the user had already entered for
  // today, right before they'd submit it.
  useEffect(() => {
    let cancelled = false
    fetchPrescribedExercises(sessionType)
      .then((exercises) => {
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
        setCustomExercises([])
      })
      .catch((err: unknown) => {
        if (!cancelled) console.error("Failed to load prescribed exercises:", err)
      })
    return () => {
      cancelled = true
    }
  }, [sessionType])

  // Checks for an already-logged entry for this exact (date, sessionType) --
  // correctly depends on both, unlike the reset effect above.
  useEffect(() => {
    let cancelled = false
    setExistingCheckError(null)
    fetchExistingCalisthenics(date, sessionType)
      .then((r) => {
        if (!cancelled) setExisting(r)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        console.error("Failed to check for an existing calisthenics entry:", err)
        setExisting(null)
        setExistingCheckError(err instanceof Error ? err.message : "Could not reach the API.")
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

  function updateCustomExercise(
    id: string,
    field: keyof ExerciseInput,
    value: string | number,
  ) {
    setCustomExercises((prev) =>
      prev.map((ex) => (ex.id === id ? { ...ex, [field]: value } : ex)),
    )
  }

  function addCustomExercise() {
    setCustomExercises((prev) => [...prev, newCustomExercise()])
  }

  function removeCustomExercise(id: string) {
    setCustomExercises((prev) => prev.filter((ex) => ex.id !== id))
  }

  async function handleSubmit() {
    setStatus(null)
    const exercises = [
      ...exerciseInputs
        .filter((ex) => ex.sets > 0)
        .map((ex) => ({
          exercise: ex.name,
          sets: ex.sets,
          reps: ex.reps || null,
          added_weight_kg: ex.addedWeight || null,
          notes: null,
        })),
      // Blank-named rows (added but never filled in) are silently dropped
      // rather than saved as an unnamed exercise -- same "blank to skip"
      // permissiveness as the prescribed rows above, just gated on name
      // instead of sets since a custom row starts with neither.
      ...customExercises
        .filter((ex) => ex.name.trim() && ex.sets > 0)
        .map((ex) => ({
          exercise: ex.name.trim(),
          sets: ex.sets,
          reps: ex.reps || null,
          added_weight_kg: ex.addedWeight || null,
          notes: null,
        })),
    ]
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

      {existingCheckError && (
        <p className="text-xs text-muted-foreground">
          Couldn&apos;t check for an existing entry: {existingCheckError}
        </p>
      )}

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

        {customExercises.map((ex) => (
          <div key={ex.id} className="flex items-start gap-2">
            <div className="flex-1 space-y-1.5">
              <Input
                placeholder="Exercise name (e.g. push-ups)"
                value={ex.name}
                onChange={(e) => updateCustomExercise(ex.id, "name", e.target.value)}
              />
              <div className="grid grid-cols-3 gap-2">
                <Input
                  type="number"
                  min={0}
                  max={20}
                  placeholder="Sets"
                  value={ex.sets || ""}
                  onChange={(e) => updateCustomExercise(ex.id, "sets", Number(e.target.value))}
                />
                <Input
                  type="number"
                  min={0}
                  max={100}
                  placeholder="Reps"
                  value={ex.reps || ""}
                  onChange={(e) => updateCustomExercise(ex.id, "reps", Number(e.target.value))}
                />
                <Input
                  type="number"
                  min={0}
                  max={100}
                  step={0.5}
                  placeholder="Added kg"
                  value={ex.addedWeight || ""}
                  onChange={(e) =>
                    updateCustomExercise(ex.id, "addedWeight", Number(e.target.value))
                  }
                />
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              className="mt-0.5 text-muted-foreground hover:text-[var(--band-red)]"
              onClick={() => removeCustomExercise(ex.id)}
              aria-label="Remove exercise"
            >
              <X className="size-3.5" />
            </Button>
          </div>
        ))}

        <Button variant="outline" size="sm" onClick={addCustomExercise}>
          <Plus className="size-3.5" />
          Add exercise
        </Button>

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
