import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { AppSidebar } from "@/components/dashboard/AppSidebar";
import { TopHeader } from "@/components/dashboard/TopHeader";
import { CaseDetailPanel } from "@/components/dashboard/CaseDetailPanel";
import { ReasoningPanel } from "@/components/dashboard/ReasoningPanel";
import { QueueInsights } from "@/components/dashboard/QueueInsights";
import { AnalyticsSection } from "@/components/dashboard/AnalyticsSection";
import { useSharedLiveQueue } from "@/hooks/useSharedLiveQueue";

export const Route = createFileRoute("/analytics")({
  head: () => ({
    meta: [
      { title: "Analytics — Agentic AI CT Prioritisation" },
      {
        name: "description",
        content: "Operational analytics and demand-aware queue insights",
      },
    ],
  }),
  component: AnalyticsPage,
});

function AnalyticsPage() {
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const { queue, caseRecords, queueEvents } = useSharedLiveQueue();

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="bg-background">
        <TopHeader />

        <div className="grid flex-1 gap-6 p-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:p-6">
          <main className="min-w-0 space-y-6">
            <div>
              <h2 className="text-xl font-semibold tracking-tight text-foreground">Analytics</h2>
              <p className="mt-1 text-xs text-muted-foreground">Demand-aware queue insights and operational analytics</p>
            </div>

            <section>
              <div className="mb-3">
                <h3 className="text-sm font-semibold tracking-tight text-foreground">
                  Demand-aware queue insights
                </h3>
                <p className="text-xs text-muted-foreground">
                  Operational intelligence shaping the next 90 minutes
                </p>
              </div>
              <QueueInsights queue={queue} />
            </section>

            <AnalyticsSection />
          </main>

          <aside className="flex flex-col gap-4 lg:sticky lg:top-[72px] lg:h-[calc(100vh-96px)] lg:self-start">
            <div className="lg:min-h-[400px] lg:flex-1 lg:basis-[55%] min-h-0">
              <CaseDetailPanel
                selectedCaseId={selectedCaseId}
                caseRecords={caseRecords}
                queueEvents={queueEvents}
              />
            </div>
            <div className="min-h-0 lg:flex-1 lg:basis-[45%]">
              <ReasoningPanel entries={queueEvents} caseRecords={caseRecords} />
            </div>
          </aside>
        </div>
      </SidebarInset>
      <Toaster position="top-right" />
    </SidebarProvider>
  );
}

export default AnalyticsPage;
