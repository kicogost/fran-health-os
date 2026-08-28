import { TodayPage } from "@/pages/Today"

// Single page for now (ADR 0005 phased migration: Today first, the rest of
// the 6-page Streamlit scope follows once this one is reviewed). A router
// (react-router) gets added when there's a second page to route to, not
// before -- no unused routing scaffolding sitting around.
function App() {
  return <TodayPage />
}

export default App
