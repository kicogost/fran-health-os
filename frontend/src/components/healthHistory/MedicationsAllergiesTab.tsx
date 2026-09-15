import { useEffect, useState } from "react"
import { Pill, ShieldAlert } from "lucide-react"
import {
  fetchAllergies,
  fetchExistingAllergy,
  fetchMedications,
  saveAllergy,
  saveMedication,
} from "@/lib/api"
import { todayLocal } from "@/lib/date"
import { CARD_CLASS, CARD_CLASS_FLAT } from "@/lib/styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import type { AllergyRow, AllergySeverity, MedicationRow, MedicationType } from "@/types/healthHistory"

const MED_TYPES: { value: MedicationType; label: string }[] = [
  { value: "medication", label: "Medication" },
  { value: "supplement", label: "Supplement" },
]

const SEVERITIES: { value: AllergySeverity; label: string }[] = [
  { value: "mild", label: "Mild" },
  { value: "moderate", label: "Moderate" },
  { value: "severe", label: "Severe" },
]

/** A Select that can genuinely represent "not specified" -- Radix Select
 * items can't carry an empty-string value, so "skip" is the sentinel,
 * mapped to/from `null` at the boundary. Same pattern LogIllnessTab's
 * TriStateSelect already established for this exact problem elsewhere in
 * the Log page.
 */
function OptionalSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string | null
  onChange: (v: string | null) => void
  options: { value: string; label: string }[]
}) {
  return (
    <div>
      <Label>{label}</Label>
      <Select value={value ?? "skip"} onValueChange={(v) => onChange(v === "skip" ? null : v)}>
        <SelectTrigger className="w-full mt-1">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="skip">Not specified</SelectItem>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function MedicationsSection() {
  const [name, setName] = useState("")
  const [medType, setMedType] = useState<MedicationType>("supplement")
  const [dosage, setDosage] = useState("")
  const [frequency, setFrequency] = useState("")
  const [startDate, setStartDate] = useState(todayLocal())
  const [endDate, setEndDate] = useState("")
  const [notes, setNotes] = useState("")
  const [meds, setMeds] = useState<MedicationRow[] | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function refresh() {
    fetchMedications()
      .then((rows) => {
        setMeds(rows)
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
    if (!name.trim()) {
      setStatus({ kind: "error", message: "Name is required." })
      return
    }
    try {
      await saveMedication({
        name: name.trim(),
        type: medType,
        dosage: dosage.trim() || null,
        frequency: frequency.trim() || null,
        start_date: startDate,
        end_date: endDate || null,
        notes: notes.trim() || null,
      })
      setStatus({ kind: "success", message: `Logged: ${name} (${medType})` })
      setName("")
      setDosage("")
      setFrequency("")
      setEndDate("")
      setNotes("")
      refresh()
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Failed to save." })
    }
  }

  return (
    <div className="space-y-4">
      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="med-name">Name</Label>
            <Input
              id="med-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1"
              placeholder="e.g. Vitamin D3"
            />
          </div>
          <div>
            <Label>Type</Label>
            <Select value={medType} onValueChange={(v) => setMedType(v as MedicationType)}>
              <SelectTrigger className="w-full mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MED_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="med-dosage">Dosage</Label>
            <Input
              id="med-dosage"
              value={dosage}
              onChange={(e) => setDosage(e.target.value)}
              className="mt-1"
              placeholder="e.g. 500mg"
            />
          </div>
          <div>
            <Label htmlFor="med-frequency">Frequency</Label>
            <Input
              id="med-frequency"
              value={frequency}
              onChange={(e) => setFrequency(e.target.value)}
              className="mt-1"
              placeholder="e.g. daily"
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="med-start">Start date</Label>
            <Input
              id="med-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="med-end">End date (blank if still taking)</Label>
            <Input
              id="med-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="mt-1"
            />
          </div>
        </div>
        <div>
          <Label htmlFor="med-notes">Notes</Label>
          <Textarea
            id="med-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Log medication / supplement</Button>
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
          <Pill className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Medications &amp; supplements
          </p>
        </div>
        {loadError && <p className="text-sm text-muted-foreground">Couldn&apos;t load: {loadError}</p>}
        {!loadError && meds && meds.length === 0 && (
          <p className="text-sm text-muted-foreground">Nothing logged yet.</p>
        )}
        {meds && meds.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="pb-2 pr-4 font-medium">Name</th>
                  <th className="pb-2 pr-4 font-medium">Type</th>
                  <th className="pb-2 pr-4 font-medium">Dosage</th>
                  <th className="pb-2 pr-4 font-medium">Frequency</th>
                  <th className="pb-2 font-medium">Course</th>
                </tr>
              </thead>
              <tbody>
                {meds.map((m) => (
                  <tr
                    key={m.id}
                    className="border-b border-border/50 last:border-0 even:bg-accent/20"
                  >
                    <td className="py-2 pr-4 text-foreground">{m.name}</td>
                    <td className="py-2 pr-4 text-muted-foreground capitalize">{m.type}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{m.dosage ?? "—"}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{m.frequency ?? "—"}</td>
                    <td className="py-2 text-muted-foreground text-xs">
                      {m.start_date} → {m.end_date ?? "ongoing"}
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

function AllergiesSection() {
  const [allergen, setAllergen] = useState("")
  const [reaction, setReaction] = useState("")
  const [severity, setSeverity] = useState<string | null>(null)
  const [dateIdentified, setDateIdentified] = useState("")
  const [notes, setNotes] = useState("")
  const [existing, setExisting] = useState<{ severity: AllergySeverity | null } | null>(null)
  const [allergies, setAllergies] = useState<AllergyRow[] | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function refreshList() {
    fetchAllergies()
      .then((rows) => {
        setAllergies(rows)
        setLoadError(null)
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : "Could not reach the API.")
      })
  }

  useEffect(() => {
    refreshList()
  }, [])

  // Same-shape overwrite-warning check as the daily Log tabs, keyed on
  // `allergen` (the table's real natural key) rather than a date.
  useEffect(() => {
    const trimmed = allergen.trim()
    if (!trimmed) {
      setExisting(null)
      return
    }
    let cancelled = false
    fetchExistingAllergy(trimmed)
      .then((r) => {
        if (!cancelled) setExisting(r)
      })
      .catch(() => {
        if (!cancelled) setExisting(null)
      })
    return () => {
      cancelled = true
    }
  }, [allergen])

  async function handleSubmit() {
    setStatus(null)
    const trimmed = allergen.trim()
    if (!trimmed) {
      setStatus({ kind: "error", message: "Allergen is required." })
      return
    }
    try {
      await saveAllergy({
        allergen: trimmed,
        reaction: reaction.trim() || null,
        severity: severity as AllergySeverity | null,
        date_identified: dateIdentified || null,
        notes: notes.trim() || null,
      })
      setStatus({ kind: "success", message: `Logged: ${trimmed}` })
      setAllergen("")
      setReaction("")
      setSeverity(null)
      setDateIdentified("")
      setNotes("")
      refreshList()
    } catch (err) {
      setStatus({ kind: "error", message: err instanceof Error ? err.message : "Failed to save." })
    }
  }

  return (
    <div className="space-y-4">
      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="allergy-allergen">Allergen</Label>
            <Input
              id="allergy-allergen"
              value={allergen}
              onChange={(e) => setAllergen(e.target.value)}
              className="mt-1"
              placeholder="e.g. peanuts"
            />
          </div>
          <OptionalSelect
            label="Severity"
            value={severity}
            onChange={setSeverity}
            options={SEVERITIES}
          />
        </div>

        {existing && (
          <p className="text-sm text-[var(--band-amber)] rounded-lg border border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10 px-3 py-2">
            Already logged (severity={existing.severity ?? "—"}). Submitting again will overwrite
            it.
          </p>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="allergy-reaction">Reaction</Label>
            <Input
              id="allergy-reaction"
              value={reaction}
              onChange={(e) => setReaction(e.target.value)}
              className="mt-1"
              placeholder="e.g. hives"
            />
          </div>
          <div>
            <Label htmlFor="allergy-date-identified">Date identified</Label>
            <Input
              id="allergy-date-identified"
              type="date"
              value={dateIdentified}
              onChange={(e) => setDateIdentified(e.target.value)}
              className="mt-1"
            />
          </div>
        </div>
        <div>
          <Label htmlFor="allergy-notes">Notes</Label>
          <Textarea
            id="allergy-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Log allergy</Button>
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
          <ShieldAlert className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Allergies
          </p>
        </div>
        {loadError && <p className="text-sm text-muted-foreground">Couldn&apos;t load: {loadError}</p>}
        {!loadError && allergies && allergies.length === 0 && (
          <p className="text-sm text-muted-foreground">No allergies logged yet.</p>
        )}
        {allergies && allergies.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="pb-2 pr-4 font-medium">Allergen</th>
                  <th className="pb-2 pr-4 font-medium">Reaction</th>
                  <th className="pb-2 pr-4 font-medium">Severity</th>
                  <th className="pb-2 font-medium">Identified</th>
                </tr>
              </thead>
              <tbody>
                {allergies.map((a) => (
                  <tr
                    key={a.allergen}
                    className="border-b border-border/50 last:border-0 even:bg-accent/20"
                  >
                    <td className="py-2 pr-4 text-foreground">{a.allergen}</td>
                    <td className="py-2 pr-4 text-muted-foreground">{a.reaction ?? "—"}</td>
                    <td className="py-2 pr-4 text-muted-foreground capitalize">
                      {a.severity ?? "—"}
                    </td>
                    <td className="py-2 text-muted-foreground">{a.date_identified ?? "—"}</td>
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

/** Medications/supplements and allergies share one tab (keeps the tab list
 * uncluttered, per the design ask), stacked as two independent sections --
 * they're two different tables with two different natural-key/overwrite
 * behaviors (medications: none, fresh insert every time; allergies:
 * `allergen`, upsert with a warning), not one merged form.
 */
export function MedicationsAllergiesTab() {
  return (
    <div className="space-y-8">
      <MedicationsSection />
      <div className="border-t border-border" />
      <AllergiesSection />
    </div>
  )
}
