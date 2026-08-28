import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { LogBjjTab } from "@/components/log/LogBjjTab"
import { LogCalisthenicsTab } from "@/components/log/LogCalisthenicsTab"
import { LogWellnessTab } from "@/components/log/LogWellnessTab"
import { LogWaistTab } from "@/components/log/LogWaistTab"

/** Log — BJJ session, calisthenics, daily wellness, waist measurement.
 * Same rules as the CLI scripts and the Streamlit page these mirror:
 * upsert on the table's natural key, warn before overwriting an existing
 * entry for the SELECTED date (each tab fetches the existing entry
 * whenever its date/type state changes — no Streamlit-form-batching
 * footgun here since React state is always live).
 */
export function LogPage() {
  return (
    <div className="max-w-4xl mx-auto p-6 space-y-3">
      <h1 className="text-2xl font-semibold text-foreground tracking-tight mb-1">Log</h1>

      <Tabs defaultValue="bjj">
        <TabsList>
          <TabsTrigger value="bjj">BJJ session</TabsTrigger>
          <TabsTrigger value="calisthenics">Calisthenics</TabsTrigger>
          <TabsTrigger value="wellness">Daily wellness</TabsTrigger>
          <TabsTrigger value="waist">Waist</TabsTrigger>
        </TabsList>
        <TabsContent value="bjj" className="pt-4">
          <LogBjjTab />
        </TabsContent>
        <TabsContent value="calisthenics" className="pt-4">
          <LogCalisthenicsTab />
        </TabsContent>
        <TabsContent value="wellness" className="pt-4">
          <LogWellnessTab />
        </TabsContent>
        <TabsContent value="waist" className="pt-4">
          <LogWaistTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
