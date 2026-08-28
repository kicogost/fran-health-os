import { Dumbbell, Home, PenLine, Stethoscope, TrendingUp, Trophy } from "lucide-react"
import { NavLink } from "react-router-dom"

// Same 6-page scope and order as the Streamlit dashboard's app.py (Today,
// Trends, Training, Comp Prep, Log, Data Health) -- mirrored deliberately,
// per ADR 0005, not reshuffled just because the framework changed.
const NAV_ITEMS = [
  { to: "/", label: "Today", icon: Home, end: true },
  { to: "/trends", label: "Trends", icon: TrendingUp },
  { to: "/training", label: "Training", icon: Dumbbell },
  { to: "/comp-prep", label: "Comp Prep", icon: Trophy },
  { to: "/log", label: "Log", icon: PenLine },
  { to: "/data-health", label: "Data Health", icon: Stethoscope },
]

/** Fixed-width left sidebar (240px -- ui-ux-pro-max-skill's own
 * Data-Dense Dashboard checklist names this exact width for a filter/nav
 * sidebar on this style of layout). Local-only personal app, one user, so
 * no auth/account UI here -- just navigation.
 */
export function Sidebar() {
  return (
    <aside className="w-60 shrink-0 border-r border-border bg-card/50 flex flex-col">
      <div className="px-5 py-5">
        <p className="text-base font-semibold text-foreground tracking-tight">Health OS</p>
        <p className="text-xs text-muted-foreground mt-0.5">Francisco</p>
      </div>
      <nav className="flex-1 px-3 space-y-0.5">
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              [
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-accent text-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
              ].join(" ")
            }
          >
            <Icon className="h-4 w-4" strokeWidth={2} />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
