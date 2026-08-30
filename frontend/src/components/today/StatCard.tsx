import type { LucideIcon } from "lucide-react"
import { CARD_CLASS_FLAT } from "@/lib/styles"

interface StatCardProps {
  icon: LucideIcon
  label: string
  value: string
  caption?: string
  children?: React.ReactNode
}

/** A generic small metric card -- sleep, weight, comp countdown all share
 * this exact shape (icon + title + big value + a line of context
 * underneath). The icon is a real lucide-react component, never an emoji
 * character as an icon -- a real anti-pattern the design-data pass caught
 * (see CLAUDE.md's "Today page design pass" entry).
 */
export function StatCard({ icon: Icon, label, value, caption, children }: StatCardProps) {
  return (
    <div className={`${CARD_CLASS_FLAT} p-4 min-w-0`}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </p>
      </div>
      <p className="text-2xl font-semibold tabular-nums tracking-tight text-foreground">{value}</p>
      {caption && <p className="text-sm text-muted-foreground mt-1">{caption}</p>}
      {children}
    </div>
  )
}
