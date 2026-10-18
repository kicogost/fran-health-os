import { useEffect, useState } from "react"
import type { LucideIcon } from "lucide-react"
import {
  BedDouble,
  Bike,
  Brain,
  CalendarClock,
  ClipboardCheck,
  Coffee,
  Dumbbell,
  Moon,
  MoonStar,
  PersonStanding,
  Sunrise,
  Swords,
  Utensils,
} from "lucide-react"
import { ApiError, fetchSchedule } from "@/lib/api"
import { CARD_CLASS, CARD_CLASS_FLAT } from "@/lib/styles"
import type { BlockKind, ScheduleBlock, ScheduleDay, SchedulePayload } from "@/types/schedule"

const DAY_SHORT: Record<string, string> = {
  monday: "Mon",
  tuesday: "Tue",
  wednesday: "Wed",
  thursday: "Thu",
  friday: "Fri",
  saturday: "Sat",
  sunday: "Sun",
}

// Colours reuse the existing band tokens -- no new palette.
const KIND_STYLE: Record<BlockKind, { icon: LucideIcon; color: string }> = {
  routine: { icon: Sunrise, color: "var(--band-amber)" },
  mind: { icon: Brain, color: "var(--band-blue)" },
  mobility: { icon: PersonStanding, color: "var(--band-blue)" },
  log: { icon: ClipboardCheck, color: "var(--muted-foreground)" },
  meal: { icon: Utensils, color: "var(--band-green)" },
  coffee: { icon: Coffee, color: "var(--muted-foreground)" },
  training: { icon: Dumbbell, color: "var(--band-red)" },
  rest: { icon: BedDouble, color: "var(--band-green)" },
  wind_down: { icon: MoonStar, color: "var(--band-blue)" },
  sleep: { icon: Moon, color: "var(--band-blue)" },
}

function iconFor(block: ScheduleBlock): LucideIcon {
  if (block.kind === "training") {
    const t = block.title.toLowerCase()
    if (t.includes("bjj")) return Swords
    if (t.includes("bike")) return Bike
  }
  return KIND_STYLE[block.kind].icon
}

function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number)
  return h * 60 + m
}

type BlockState = "past" | "now" | "next" | "upcoming"

/** Now/next markers for today's view only. A timed block is "now" while
 * the clock is inside it; a point-in-time block (a meal, coffee) is past
 * once its time has gone by. */
function blockStates(blocks: ScheduleBlock[], nowMin: number): BlockState[] {
  const states: BlockState[] = blocks.map((b) => {
    const start = toMinutes(b.start)
    const end = b.end ? toMinutes(b.end) : start
    if (b.end && start <= nowMin && nowMin < end) return "now"
    return end <= nowMin ? "past" : "upcoming"
  })
  const nextIdx = states.findIndex((s) => s === "upcoming")
  if (nextIdx >= 0) states[nextIdx] = "next"
  return states
}

function Timeline({ day, nowMin }: { day: ScheduleDay; nowMin: number | null }) {
  const states = nowMin === null ? null : blockStates(day.blocks, nowMin)
  return (
    <ol className="relative">
      {day.blocks.map((block, i) => {
        const state = states?.[i]
        const Icon = iconFor(block)
        const color = KIND_STYLE[block.kind].color
        const isTraining = block.kind === "training"
        return (
          <li
            key={`${block.start}-${block.title}`}
            className={[
              "flex gap-3 py-2.5 px-2 rounded-lg",
              state === "past" ? "opacity-40" : "",
              state === "now" ? "bg-accent/60" : "",
            ].join(" ")}
          >
            <span className="w-24 shrink-0 text-sm tabular-nums text-muted-foreground pt-0.5">
              {block.start}
              {block.end ? `–${block.end}` : ""}
            </span>
            <Icon className="h-4 w-4 shrink-0 mt-0.5" style={{ color }} strokeWidth={2} />
            <div className="min-w-0">
              <p
                className={[
                  "text-sm text-foreground",
                  isTraining ? "font-semibold" : "font-medium",
                ].join(" ")}
              >
                {block.title}
                {state === "now" && (
                  <span className="ml-2 rounded-full bg-[var(--band-blue)] px-2 py-0.5 text-[10px] font-semibold uppercase text-[#0a0a0b]">
                    Now
                  </span>
                )}
                {state === "next" && (
                  <span className="ml-2 rounded-full border border-[var(--band-blue)] px-2 py-0.5 text-[10px] font-semibold uppercase text-[var(--band-blue)]">
                    Next
                  </span>
                )}
              </p>
              {block.notes && <p className="text-xs text-muted-foreground mt-0.5">{block.notes}</p>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function currentMinutes(): number {
  const d = new Date()
  return d.getHours() * 60 + d.getMinutes()
}

export function SchedulePage() {
  const [data, setData] = useState<SchedulePayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [nowMin, setNowMin] = useState(currentMinutes)

  useEffect(() => {
    let cancelled = false
    fetchSchedule()
      .then((payload) => {
        if (!cancelled) setData(payload)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not reach the API.")
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => setNowMin(currentMinutes()), 60_000)
    return () => window.clearInterval(id)
  }, [])

  if (error)
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className={`${CARD_CLASS} p-5`}>
          <p className="text-sm text-foreground">{error}</p>
        </div>
      </div>
    )
  if (!data) return <p className="text-muted-foreground p-8">Loading...</p>

  const selectedDay = selected ?? data.today
  const day = data.days.find((d) => d.day === selectedDay) ?? data.days[0]

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <CalendarClock className="h-5 w-5 text-muted-foreground" strokeWidth={2} />
        <h1 className="text-2xl font-semibold text-foreground tracking-tight">Schedule</h1>
      </div>
      <p className="text-sm text-muted-foreground">
        Wake {data.wake} · Eating {data.eating_window[0]}–{data.eating_window[1]} · Lights out{" "}
        {data.lights_out}
      </p>

      <div className="flex flex-wrap gap-1 rounded-full border border-border p-1 w-fit">
        {data.days.map((d) => (
          <button
            key={d.day}
            type="button"
            onClick={() => setSelected(d.day)}
            className={[
              "px-3 py-1 text-sm rounded-full transition-colors",
              d.day === selectedDay
                ? "bg-[var(--band-blue)] text-[#0a0a0b] font-medium"
                : "text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            {DAY_SHORT[d.day]}
            {d.is_today ? " ·" : ""}
          </button>
        ))}
      </div>

      <div className={`${CARD_CLASS} p-4`}>
        <div className="flex items-baseline justify-between mb-2 px-2">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {day.is_today ? "Today" : DAY_SHORT[day.day]} ·{" "}
            <span className="capitalize">{day.day}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            Eating {day.eating_window[0]}–{day.eating_window[1]}
          </p>
        </div>
        <Timeline day={day} nowMin={day.is_today ? nowMin : null} />
      </div>

      <div className={`${CARD_CLASS_FLAT} p-4`}>
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
          Week at a glance
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-7 gap-2">
          {data.days.map((d) => {
            const sessions = d.blocks.filter((b) => b.kind === "training" || b.kind === "rest")
            return (
              <button
                key={d.day}
                type="button"
                onClick={() => setSelected(d.day)}
                className={[
                  "text-left rounded-lg border p-2 transition-colors",
                  d.day === selectedDay
                    ? "border-[var(--band-blue)]"
                    : "border-border hover:border-muted-foreground",
                ].join(" ")}
              >
                <p className="text-xs font-semibold text-foreground">{DAY_SHORT[d.day]}</p>
                {sessions.length === 0 ? (
                  <p className="text-xs text-muted-foreground mt-1">Rest</p>
                ) : (
                  sessions.map((b) => (
                    <p key={b.start} className="text-xs text-muted-foreground mt-1">
                      <span className="tabular-nums">{b.start}</span> {b.title}
                    </p>
                  ))
                )}
              </button>
            )
          })}
        </div>
      </div>

      {data.starts && (
        <p className="text-xs text-muted-foreground">
          Post-comp week, in force from {data.starts}. Edit times in config/athlete.yaml
          (weekly_architecture.daily_routine).
        </p>
      )}
    </div>
  )
}
