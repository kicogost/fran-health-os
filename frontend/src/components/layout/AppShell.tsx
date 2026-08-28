import { Outlet } from "react-router-dom"
import { Sidebar } from "@/components/layout/Sidebar"

/** Sidebar + routed page content. One shell for all 6 pages so navigation,
 * background, and spacing stay identical everywhere -- individual pages
 * only own their own content, never the page chrome around it.
 */
export function AppShell() {
  return (
    <div className="flex min-h-screen bg-background">
      <Sidebar />
      <main className="flex-1 min-w-0">
        <Outlet />
      </main>
    </div>
  )
}
