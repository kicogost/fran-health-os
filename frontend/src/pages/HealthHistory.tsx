import { HeartPulse } from "lucide-react"
import { BloodworkTab } from "@/components/healthHistory/BloodworkTab"
import { FamilyHistoryTab } from "@/components/healthHistory/FamilyHistoryTab"
import { MedicalEventsTab } from "@/components/healthHistory/MedicalEventsTab"
import { MedicationsAllergiesTab } from "@/components/healthHistory/MedicationsAllergiesTab"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

/** Health History (2026-09-14) -- general medical record-keeping, separate
 * from the daily "Log" page: bloodwork, medical events, medications/
 * allergies, and family history are occasional records (a handful of times
 * a year), not a daily habit, so they get their own page with their own
 * sub-tabs rather than a 6th tab bolted onto Log -- see CLAUDE.md's dated
 * section for the full reasoning. Each tab pairs a simple add-a-record
 * form with a real list/table of what's already logged, same visual
 * language (CARD_CLASS/CARD_CLASS_FLAT) as the rest of the app.
 */
export function HealthHistoryPage() {
  return (
    <div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <HeartPulse className="h-5 w-5 text-muted-foreground" strokeWidth={2} />
        <h1 className="text-2xl font-semibold text-foreground tracking-tight">Health History</h1>
      </div>

      <Tabs defaultValue="bloodwork">
        <TabsList>
          <TabsTrigger value="bloodwork">Bloodwork</TabsTrigger>
          <TabsTrigger value="medical-events">Medical events</TabsTrigger>
          <TabsTrigger value="medications-allergies">Medications &amp; allergies</TabsTrigger>
          <TabsTrigger value="family-history">Family history</TabsTrigger>
        </TabsList>
        <TabsContent value="bloodwork" className="pt-4">
          <BloodworkTab />
        </TabsContent>
        <TabsContent value="medical-events" className="pt-4">
          <MedicalEventsTab />
        </TabsContent>
        <TabsContent value="medications-allergies" className="pt-4">
          <MedicationsAllergiesTab />
        </TabsContent>
        <TabsContent value="family-history" className="pt-4">
          <FamilyHistoryTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
