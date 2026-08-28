import { lazy, Suspense } from "react"
import { BrowserRouter, Route, Routes } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"

// Lazy-loaded per route -- recharts (Trends/Training/Comp Prep) is a large
// dependency that shouldn't be in the initial bundle just to show the Today
// page. Each page's own chunk loads only when its route is actually visited.
const TodayPage = lazy(() => import("@/pages/Today").then((m) => ({ default: m.TodayPage })))
const TrendsPage = lazy(() => import("@/pages/Trends").then((m) => ({ default: m.TrendsPage })))
const TrainingPage = lazy(() =>
  import("@/pages/Training").then((m) => ({ default: m.TrainingPage })),
)
const CompPrepPage = lazy(() =>
  import("@/pages/CompPrep").then((m) => ({ default: m.CompPrepPage })),
)
const LogPage = lazy(() => import("@/pages/Log").then((m) => ({ default: m.LogPage })))
const DataHealthPage = lazy(() =>
  import("@/pages/DataHealth").then((m) => ({ default: m.DataHealthPage })),
)

function PageFallback() {
  return <p className="text-muted-foreground p-8">Loading...</p>
}

// Same 6-page scope and order as the Streamlit dashboard (ADR 0005) --
// mirrored, not reshuffled.
function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<TodayPage />} />
            <Route path="trends" element={<TrendsPage />} />
            <Route path="training" element={<TrainingPage />} />
            <Route path="comp-prep" element={<CompPrepPage />} />
            <Route path="log" element={<LogPage />} />
            <Route path="data-health" element={<DataHealthPage />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App
