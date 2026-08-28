# 5. Migrate the dashboard off Streamlit, after Phase 7

Date: 2026-08-28
Status: Accepted (migration itself not yet started — scheduled after Phase 7)

## Context

Phase 5 shipped a full 6-page Streamlit dashboard, iterated visually three times in one
session: an initial WHOOP-inspired ring/card redesign, a pass applying IBM Carbon's
published `g100` dark-theme tokens, and a round of concrete fixes found via real
screenshots (Chrome's headless `--screenshot` flag — no browser/screenshot tool exists
in this environment otherwise, so this was the first time the dashboard was actually
*seen* rather than described). Each round drew on a legitimate, well-regarded reference
(WHOOP's own app, Linear/Vercel's minimal-dark philosophy, Carbon's real accessibility-
tested tokens, a fourth design-systems methodology repo). Francisco's reaction after
all four: still not "slick."

That pattern — four solid, legitimate design references, still not landing — stopped
looking like "wrong reference material" and started looking like a real ceiling in
Streamlit itself. Streamlit is a data-app framework, not a general UI toolkit: its
native widgets (buttons, tabs, sliders, selectboxes, the sidebar, `st.form`) render
through fixed internal HTML/CSS that injected CSS can restyle at the margins (colors,
spacing, fonts) but can't fundamentally rebuild. The result reads as "a nicely themed
Streamlit app," not indistinguishable from a purpose-built app — which is the actual
bar the WHOOP/Linear/Vercel references were setting.

## Decision

**Migrate the dashboard to a real frontend stack (React + Tailwind, likely with
shadcn/ui component primitives — the same stack the design-system references
Francisco pointed at actually target) once Phase 7 is done, not before.**

## Reasoning for the sequencing (Phase 7 first)

- Phase 7 (`coach/rules.py`, `coach/briefing.py`) is pure backend logic — deterministic
  rules producing a decision + reasons, narrated into a briefing. It has zero UI
  dependency and doesn't touch the dashboard at all. Building it doesn't cost anything
  in frontend-rework terms regardless of when the frontend migration happens.
- The frontend migration is a genuinely large, separate project: choosing/setting up
  the stack, standing up a local API layer to bridge the new JS frontend to the
  existing Python business logic (`metrics/`, `coach/`, `core/db.py` all stay exactly
  as they are — only the presentation layer changes), and rebuilding all 6 pages'
  charts/forms/layout from scratch. It deserves its own focused effort, not a rush
  job squeezed in ahead of something as substantively important as the coaching engine.
- Doing Phase 7 first means the new frontend's coaching/guidance UI gets built ONCE,
  against Phase 7's real, final output shape (decision + reasons + safety-rail flags +
  structural-trigger warnings) — not against `views/today.py`'s current placeholder
  `(session_type, band) -> string` lookup table, which Phase 7 will replace outright.
  Building the new frontend first would mean designing its coaching component against
  a shape that's about to change underneath it.

## Alternatives considered

- **Migrate now, before Phase 7.** Rejected: would mean building the new frontend's
  most important page (the coaching/guidance display) against data that's known to be
  a temporary placeholder, guaranteeing rework once Phase 7 lands.
- **Keep investing further in Streamlit CSS overrides.** Rejected, based on direct
  evidence: three rounds of increasingly serious visual work (ring gauges replacing
  progress bars, Carbon's real tokens, concrete bugs found and fixed via actual
  screenshots) still didn't reach "slick" — diminishing returns on the same approach,
  not a reference-material problem.
- **Stay on Streamlit permanently, accept its ceiling.** Considered but Francisco was
  explicit that visual polish matters enough to spend more time on, once asked directly
  whether to keep iterating within Streamlit vs. change the framework.

## Consequences

- Local-first (design principle 1) must be preserved through the migration: no cloud
  services, no hosted frontend. The new stack should run entirely locally — a local
  API server (likely FastAPI, given it's Python and can import the existing `core`/
  `metrics`/`coach` modules directly rather than needing a second language runtime for
  business logic) serving the React frontend, still a single local command to run.
- `src/health_os/dashboard/` (the current Streamlit app: `theme.py`, `data.py`,
  `views/*.py`) stays as-is and in active use until the migration actually happens —
  not deleted or frozen mid-improvement in the meantime.
- The migration itself is **not scoped or started** as of this ADR — stack specifics
  (Vite vs. Next.js, exact component library, how the local API layer is structured)
  are deliberately left for when that work actually begins, not decided speculatively
  now.
- Six-page scope (Today/Trends/Training/Comp Prep/Log/Data Health) and the underlying
  data-access patterns (`dashboard/data.py`'s cached loaders) transfer conceptually to
  the new frontend's API layer even though the presentation code will be rewritten
  from scratch.
