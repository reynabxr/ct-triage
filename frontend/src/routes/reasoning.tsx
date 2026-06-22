import { createFileRoute } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { AppSidebar } from "@/components/dashboard/AppSidebar";
import { TopHeader } from "@/components/dashboard/TopHeader";
import { ReasoningLog } from "../components/dashboard/ReasoningLog";
import { useSharedLiveQueue } from "@/hooks/useSharedLiveQueue";

export const Route = createFileRoute("/reasoning")({
  validateSearch: (search: Record<string, unknown>) => ({
    caseId: typeof search.caseId === "string" ? search.caseId : undefined,
    patientCode: typeof search.patientCode === "string" ? search.patientCode : undefined,
    patientName: typeof search.patientName === "string" ? search.patientName : undefined,
    eventId: typeof search.eventId === "string" ? search.eventId : undefined,
  }),
  head: () => ({
    meta: [{ title: "Reasoning Log — Agentic AI CT Prioritisation" }],
  }),
  component: ReasoningPage,
});

function ReasoningPage() {
  const { queueEvents, caseRecords } = useSharedLiveQueue();
  const search = Route.useSearch();

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="bg-background">
        <TopHeader />

        <div className="p-4 lg:p-6">
          <div className="max-w-4xl">
            <ReasoningLog
              entries={queueEvents}
              caseRecords={caseRecords}
              caseId={search.caseId}
              patientCode={search.patientCode}
              patientName={search.patientName}
              eventId={search.eventId}
            />
          </div>
        </div>
      </SidebarInset>
      <Toaster position="top-right" />
    </SidebarProvider>
  );
}
