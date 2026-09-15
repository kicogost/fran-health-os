import { useEffect, useState } from "react"
import { Users } from "lucide-react"
import { fetchExistingFamilyHistory, fetchFamilyHistory, saveFamilyHistory } from "@/lib/api"
import { CARD_CLASS, CARD_CLASS_FLAT } from "@/lib/styles"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import type { FamilyHistoryRow } from "@/types/healthHistory"

/** Family medical history -- grain: UNIQUE(relation, condition), so
 * re-logging the same fact updates it (with a warning) rather than
 * duplicating, same natural-keyed shape as Allergies.
 */
export function FamilyHistoryTab() {
  const [relation, setRelation] = useState("")
  const [condition, setCondition] = useState("")
  const [notes, setNotes] = useState("")
  const [existing, setExisting] = useState<{ notes: string | null } | null>(null)
  const [entries, setEntries] = useState<FamilyHistoryRow[] | null>(null)
  const [status, setStatus] = useState<{ kind: "success" | "error"; message: string } | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function refresh() {
    fetchFamilyHistory()
      .then((rows) => {
        setEntries(rows)
        setLoadError(null)
      })
      .catch((err: unknown) => {
        setLoadError(err instanceof Error ? err.message : "Could not reach the API.")
      })
  }

  useEffect(() => {
    refresh()
  }, [])

  useEffect(() => {
    const r = relation.trim()
    const c = condition.trim()
    if (!r || !c) {
      setExisting(null)
      return
    }
    let cancelled = false
    fetchExistingFamilyHistory(r, c)
      .then((result) => {
        if (!cancelled) setExisting(result)
      })
      .catch(() => {
        if (!cancelled) setExisting(null)
      })
    return () => {
      cancelled = true
    }
  }, [relation, condition])

  async function handleSubmit() {
    setStatus(null)
    const r = relation.trim()
    const c = condition.trim()
    if (!r || !c) {
      setStatus({ kind: "error", message: "Relation and condition are both required." })
      return
    }
    try {
      await saveFamilyHistory({ relation: r, condition: c, notes: notes.trim() || null })
      setStatus({ kind: "success", message: `Logged: ${r} — ${c}` })
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
            <Label htmlFor="family-relation">Relation</Label>
            <Input
              id="family-relation"
              value={relation}
              onChange={(e) => setRelation(e.target.value)}
              className="mt-1"
              placeholder="e.g. mother, paternal grandfather"
            />
          </div>
          <div>
            <Label htmlFor="family-condition">Condition</Label>
            <Input
              id="family-condition"
              value={condition}
              onChange={(e) => setCondition(e.target.value)}
              className="mt-1"
              placeholder="e.g. hypertension"
            />
          </div>
        </div>

        {existing && (
          <p className="text-sm text-[var(--band-amber)] rounded-lg border border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10 px-3 py-2">
            Already logged. Submitting again will overwrite its notes.
          </p>
        )}

        <div>
          <Label htmlFor="family-notes">Notes</Label>
          <Textarea
            id="family-notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="mt-1"
          />
        </div>
        <Button onClick={handleSubmit}>Log family history</Button>
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
          <Users className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Family history
          </p>
        </div>
        {loadError && <p className="text-sm text-muted-foreground">Couldn&apos;t load: {loadError}</p>}
        {!loadError && entries && entries.length === 0 && (
          <p className="text-sm text-muted-foreground">Nothing logged yet.</p>
        )}
        {entries && entries.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="pb-2 pr-4 font-medium">Relation</th>
                  <th className="pb-2 pr-4 font-medium">Condition</th>
                  <th className="pb-2 font-medium">Notes</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr
                    key={`${e.relation}-${e.condition}`}
                    className="border-b border-border/50 last:border-0 even:bg-accent/20"
                  >
                    <td className="py-2 pr-4 text-foreground capitalize">{e.relation}</td>
                    <td className="py-2 pr-4 text-foreground">{e.condition}</td>
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
