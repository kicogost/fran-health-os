import { CARD_CLASS } from "@/lib/styles"

interface StatCardProps {
  label: string
  value: string
  caption?: string
  children?: React.ReactNode
}

/** A generic small metric card -- sleep, weight, comp countdown all share
 * this exact shape (title + big value + a line of context underneath).
 */
export function StatCard({ label, value, caption, children }: StatCardProps) {
  return (
    <div className={`${CARD_CLASS} p-4 min-w-0`}>
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">
        {label}
      </p>
      <p className="text-2xl font-semibold tabular-nums text-foreground">{value}</p>
      {caption && <p className="text-sm text-muted-foreground mt-1">{caption}</p>}
      {children}
    </div>
  )
}
