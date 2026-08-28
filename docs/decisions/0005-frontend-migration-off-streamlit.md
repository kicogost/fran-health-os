# 5. Migrate the dashboard off Streamlit, after Phase 7

Date: 2026-08-28
Status: Accepted — migration complete 2026-08-28, all 6 pages (Today, Trends,
Training, Comp Prep, Log, Data Health) rebuilt and verified against the real
database; see CLAUDE.md's "Frontend migration started" / "All 6 pages built"
entries for the full detail. The Streamlit dashboard has NOT been removed —
see "Consequences" below.

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
- Six-page scope (Today/Trends/Training/Comp Prep/Log/Data Health) and the underlying
  data-access patterns (`dashboard/data.py`'s cached loaders) transfer conceptually to
  the new frontend's API layer even though the presentation code will be rewritten
  from scratch.

## Update, 2026-08-28 — migration started, stack specifics now decided

Francisco gave the go-ahead the same day. Scoped as **Today page first, phased** (his
explicit choice when asked) rather than all 6 pages before seeing anything running —
see CLAUDE.md's "Frontend migration started" entry for the full real-data-verified
result. Stack specifics this ADR deliberately deferred are now settled by actually
building it:

- **Vite**, not Next.js — this app has no SSR/routing-heavy needs (a single-user local
  dashboard), and Vite is the simpler, faster-to-iterate choice for a local SPA.
- **shadcn/ui with the Radix UI base** (not the CLI's newer "Base UI" default) — Radix
  has the longer, better-documented real-world track record; this project consistently
  favors that over bleeding-edge (same reasoning as picking `garminconnect[typed]`'s
  stable Pydantic models over hand-parsing, ADR 0004).
- **FastAPI**, confirmed — `src/health_os/api/` imports `coach`/`metrics`/`core`
  directly, zero duplication of business logic into JavaScript.
- **Same fixed dark theme** as the Streamlit dashboard's own Carbon `g100` tokens
  (`theme.py`) — no light/dark toggle; this is a personal app with one established,
  already-approved visual identity, not a product serving arbitrary viewer preference.
- Real tooling gotcha hit and fixed: `npx shadcn@latest init`/`add` wrote component
  files to a literal `./@/` directory at the project root instead of resolving the
  `@/*` → `./src/*` alias into `src/components/ui/` — confirmed by checking the actual
  file tree, not assumed. Fixed by moving the files to their correct location by hand;
  the alias itself (in `vite.config.ts` and `tsconfig.app.json`) was already correct
  and resolves fine now that the files live where it points. Recurred on every
  subsequent `shadcn add` call in this project (tabs, input, textarea, label, select,
  slider) — same fix each time, not a one-off.

## Update, 2026-08-28 — all 6 pages complete

Francisco: "you can go ahead with the rest of the front end!" after approving the
Today page's second design pass. Remaining stack decisions this ADR still hadn't
settled:

- **`react-router-dom`** for client-side routing (a real second dependency addition,
  named here per the "ask before adding a dependency" rule) — `BrowserRouter` +
  a shared `AppShell` layout route (persistent left sidebar, 240px — the exact width
  `ui-ux-pro-max-skill`'s own Data-Dense Dashboard checklist names for this style of
  nav) wrapping an `<Outlet/>`, rather than each page reimplementing navigation chrome.
- **`recharts`** for charts (Trends/Training/Comp Prep) — named as one of three
  compatible libraries (`recharts|chartjs|d3`) in the same design dataset's own
  Data-Dense Dashboard row; picked as the most idiomatic-React, least-boilerplate of
  the three. Route-level code-splitting (`React.lazy` + `Suspense` per page) keeps
  this out of the initial bundle for the Today page, which doesn't need it — caught by
  Vite's own "chunk larger than 500kB" build warning, not chased proactively.
- **The Log page's mutation endpoints** are the one place this migration added NEW
  backend surface beyond what Streamlit already had: `POST /api/log/{bjj,wellness,
  waist,calisthenics}`, each a thin wrapper over the SAME dataclasses (`core/models.py`)
  the CLI scripts and Streamlit already validated through — no second validation
  layer, a `ValueError` from a constructor becomes a 422 with the same message
  `st.error()` would have shown. `merge_subjective_log_entry()` (the hooper_index
  cross-call fix from earlier this session) is reused here too, not re-solved.
- Every page's date-based "already logged, overwrite?" check fetches fresh on every
  date/type change via a plain `useEffect` — the Streamlit-specific bug this session
  found and fixed (`st.form` batching hiding the real selected date from the check)
  has no equivalent failure mode in React, since component state is always live; noted
  here so the ORIGINAL bug's lesson isn't lost just because the new stack can't
  reproduce it.

All 6 pages verified against the real database via the same Chrome-headless-
screenshot discipline as the Today page rounds — real charts (weight/HRV/RHR trends,
CTL/ATL/TSB, load-by-sport, the weight-trajectory-vs-required-path band), real tables
(dedupe log, ingest runs), real forms rendering with today's actual date pre-filled.
Deliberately did NOT submit real data through the Log page's forms during verification
— that would write fake entries into Francisco's actual health database; the 36
backend tests covering `api/log.py` (save/get/validation/upsert/merge behavior) are
the verification of record for the write path instead.

## Consequences (updated)

- The Streamlit dashboard (`src/health_os/dashboard/`) has NOT been deleted and is
  not scheduled for removal as part of this migration — it stays available as a
  fallback / comparison reference. Deciding whether to retire it is a separate,
  future call, not bundled into "the migration is done."
- Production serving story (FastAPI serving the built `frontend/dist/` as static
  files, vs. always running two local dev processes — `npm run dev` +
  `scripts/run_api.py`) remains undecided. Fine for daily local use as-is; worth a
  decision before this is the ONLY way Francisco accesses his own data day to day.
