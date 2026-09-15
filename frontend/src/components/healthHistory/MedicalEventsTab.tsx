import { useEffect, useState } from "react"
import { HeartPulse } from "lucide-react"
import { fetchMedicalEvents, saveMedicalEvent } from "@/lib/api"
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
import type {
  MedicalEventCategory,
  MedicalEventRow,
  MedicalEventStatus,
} from "@/types/healthHistory"

const CATEGORIES: { value: MedicalEventCategory; label: string }[] = [
  { value: "condition", label: "Condition" },
  { value: "injury", label: "Injury" },
  { value: "surgery", label: "Surgery" },
  { value: "hospitalization", label: "Hospitalization" },
  { value: "other", label: "Other" },
]

const STATUSES: { value: MedicalEventStatus; label: string }[] = [
  { value: "ongoing", label: "Ongoing" },
  { value: "resolved", label: "Resolved" },
  { value: "unknown", label: "Unknown" },
]

/** Medical events -- a real chronological timeline (conditions, diagnoses,
 * injuries, surgeries, hospitalizations), differentiated by `category`
 * rather than four separate forms. No natural key: multiple real events can
 * share a date, and every submit is a fresh INSERT, never an overwrite.
 */
export function MedicalEventsTab() {
  const [date, setDate] = useState(todayLocal())
  const [category, setCategory] = useState<MedicalEventCategory>("condition")
  const [title, setTitle] = useState("")
  const [status, setStatus] = useState<MedicalEventStatus>("ongoing")
  const [resolvedDate, setResolvedDate] = useState(todayLocal())
  const [notes, setNotes] = useState("")
  const [events, setEvents] = useState<MedicalEventRow[] | null>(null)
  const [saveStatus, setSaveStatus] = useState<{
    kind: "success" | "error"
    message: string
  } | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function refresh() {
    fetchMedicalEvents()
      .then((rows) => {
        setEvents(rows)
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
    setSaveStatus(null)
    if (!title.trim()) {
      setSaveStatus({ kind: "error", message: "Title is required." })
      return
    }
    try {
      await saveMedicalEvent({
        date,
        category,
        title: title.trim(),
        status,
        resolved_date: status === "resolved" ? resolvedDate : null,
        notes: notes.trim() || null,
      })
      setSaveStatus({ kind: "success", message: `Logged: ${date} [${category}] ${title}` })
      setTitle("")
      setNotes("")
      refresh()
    } catch (err) {
      setSaveStatus({
        kind: "error",
        message: err instanceof Error ? err.message : "Failed to save.",
      })
    }
  }

  return (
    <div className="space-y-4">
      <div className={`${CARD_CLASS} p-5 space-y-4`}>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="event-date">Date</Label>
            <Input
              id="event-date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label>Category</Label>
            <Select
              value={category}
              onValueChange={(v) => setCategory(v as MedicalEventCategory)}
            >
              <SelectTrigger className="w-full mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CATEGORIES.map((c) => (
                  <SelectItem key={c.value} value={c.value}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div>
          <Label htmlFor="event-title">Title (short description)</Label>
          <Input
            id="event-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="mt-1"
            placeholder="e.g. Right knee ACL tear"
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Status</Label>
            <Select value={status} onValueChange={(v) => setStatus(v as MedicalEventStatus)}>
              <SelectTrigger className="w-full mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUSES.map((s) => (
                  <SelectItem key={s.value} value={s.value}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {status === "resolved" && (
            <div>
              <Label htmlFor="event-resolved-date">Resolved date</Label>
              <Input
                id="event-resolved-date"
                type="date"
                value={resolvedDate}
                onChange={(e) => setResolvedDate(e.target.value)}
                className="mt-1"
              />
            </div>
          )}
        </div>
        <div>
          <Label htmlFor="event-notes">Notes</Label>
          <Textarea
            id="event-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Log event</Button>
      </div>

      {saveStatus && (
        <p
          className={`text-sm px-3 py-2 rounded-lg border ${
            saveStatus.kind === "success"
              ? "text-[var(--band-green)] border-[var(--band-green)]/30 bg-[var(--band-green)]/10"
              : "text-[var(--band-red)] border-[var(--band-red)]/30 bg-[var(--band-red)]/10"
          }`}
        >
          {saveStatus.message}
        </p>
      )}

      <div className={`${CARD_CLASS_FLAT} p-4`}>
        <div className="flex items-center gap-2 mb-3">
          <HeartPulse className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Timeline
          </p>
        </div>
        {loadError && (
          <p className="text-sm text-muted-foreground">Couldn&apos;t load history: {loadError}</p>
        )}
        {!loadError && events && events.length === 0 && (
          <p className="text-sm text-muted-foreground">No medical events logged yet.</p>
        )}
        {events && events.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="pb-2 pr-4 font-medium">Date</th>
                  <th className="pb-2 pr-4 font-medium">Category</th>
                  <th className="pb-2 pr-4 font-medium">Title</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr
                    key={e.id}
                    className="border-b border-border/50 last:border-0 even:bg-accent/20"
                  >
                    <td className="py-2 pr-4 text-muted-foreground">{e.date}</td>
                    <td className="py-2 pr-4 text-foreground capitalize">{e.category}</td>
                    <td className="py-2 pr-4 text-foreground">{e.title}</td>
                    <td className="py-2 pr-4 text-muted-foreground capitalize">
                      {e.status}
                      {e.status === "resolved" && e.resolved_date ? ` (${e.resolved_date})` : ""}
                    </td>
                    <td className="py-2 text-muted-foreground text-xs">{e.notes ?? ""}</td>
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
