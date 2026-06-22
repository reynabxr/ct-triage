import { useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { AppSidebar } from "@/components/dashboard/AppSidebar";
import { TopHeader } from "@/components/dashboard/TopHeader";
import { RecommendationCard } from "@/components/dashboard/RecommendationCard";
import { LiveQueueTable } from "@/components/dashboard/LiveQueueTable";
import { CaseDetailPanel } from "@/components/dashboard/CaseDetailPanel";
import { ReasoningPanel } from "@/components/dashboard/ReasoningPanel";

import { useSharedLiveQueue } from "@/hooks/useSharedLiveQueue";
import { Button } from "@/components/ui/button";
import { FastForward, Play } from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Agent — Agentic AI CT Prioritisation" },
      {
        name: "description",
        content:
          "Real-time AI-driven CT queue prioritisation for hospital radiology departments.",
      },
    ],
  }),
  component: Dashboard,
});

function Dashboard() {
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const {
    queue,
    caseRecords,
    queueEvents,
    escalatedCases,
    isLoading,
    loadError,
    fastMode,
    toggleSpeed,
    startSimulation,
    simulationPending,
    simulationStatus,
    humanDecisionPending,
    submitHumanDecision,
  } = useSharedLiveQueue();

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="bg-background">
        <TopHeader />

        <div className="grid flex-1 gap-6 p-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:p-6">
          <main className="min-w-0 space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold tracking-tight text-foreground">Live Simulation</h2>
                {isLoading ? (
                  <p className="mt-1 text-xs text-muted-foreground">Loading live queue...</p>
                ) : loadError ? (
                  <p className="mt-1 text-xs text-risk-critical">{loadError}</p>
                ) : queue.length === 0 ? (
                  <p className="mt-1 text-xs text-risk-stable">
                    {simulationStatus.status === "running" ? "Simulation running. Waiting for next case..." : "Queue is empty. Start the simulation to feed in new cases."}
                  </p>
                ) : (
                  <p className="mt-1 text-xs text-muted-foreground">Polling the backend for queue and reasoning updates</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  onClick={() => void startSimulation()}
                  disabled={simulationPending || simulationStatus.status === "running" || simulationStatus.status === "stopping"}
                  size="sm"
                  className="gap-2"
                >
                  <Play className="h-4 w-4" fill="currentColor" />
                  {simulationPending
                    ? "Starting..."
                    : simulationStatus.status === "running"
                      ? "Simulation Running"
                      : simulationStatus.status === "completed"
                        ? "Restart Simulation"
                        : "Start Simulation"}
                </Button>
                <Button onClick={() => void toggleSpeed()} variant={fastMode ? "default" : "outline"} size="sm" className="gap-2">
                  {fastMode ? <Play className="h-4 w-4" fill="currentColor" /> : <FastForward className="h-4 w-4" />}
                  {fastMode ? "Normal Speed" : "Speed Up Simulation"}
                </Button>
              </div>
            </div>
            {loadError && queue.length === 0 && (
              <div className="rounded-xl border border-risk-critical/30 bg-risk-critical-soft px-4 py-3">
                <p className="text-sm font-semibold text-risk-critical">Backend unreachable</p>
                <p className="mt-0.5 text-xs text-risk-critical/80">
                  Start the Python API with <code className="font-mono">python3 -m api</code> and set{" "}
                  <code className="font-mono">PYTHON_API_BASE_URL</code>.
                </p>
              </div>
            )}
            <RecommendationCard
              cases={escalatedCases}
              pendingDecisions={humanDecisionPending}
              onSubmitDecision={submitHumanDecision}
            />
            <LiveQueueTable
              queue={queue}
              reasoningEntries={queueEvents}
              selectedCaseId={selectedCaseId}
              onSelectCase={setSelectedCaseId}
              simulationStatus={simulationStatus}
              isPolling={!isLoading}
            />
            {/* Demand-aware queue insights and Operational analytics moved to a separate Analytics page */}
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
              <ReasoningPanel entries={queueEvents} caseRecords={caseRecords} isSimulationRunning={simulationStatus.status === "running"} />
            </div>
          </aside>
        </div>
      </SidebarInset>
      <Toaster position="top-right" />
    </SidebarProvider>
  );
}
