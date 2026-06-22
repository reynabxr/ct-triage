import { createFileRoute } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
import { AppSidebar } from "@/components/dashboard/AppSidebar";
import { TopHeader } from "@/components/dashboard/TopHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useNotifications } from "@/hooks/useNotifications";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Agentic AI CT Prioritisation" },
      {
        name: "description",
        content: "Configure dashboard settings and preferences",
      },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const { notificationsEnabled, toggleNotifications } = useNotifications();

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="bg-background">
        <TopHeader />

        <div className="flex-1 p-4 lg:p-6">
          <div className="max-w-2xl">
            <div className="mb-8">
              <h1 className="text-3xl font-bold tracking-tight text-foreground">Settings</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Manage your dashboard preferences and notifications
              </p>
            </div>

            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Notifications</CardTitle>
                  <CardDescription>
                    Control notification settings for the dashboard
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium text-foreground">Enable Notifications</p>
                      <p className="text-sm text-muted-foreground">
                        Receive alerts about queue changes and system updates
                      </p>
                    </div>
                    <Switch
                      checked={notificationsEnabled}
                      onCheckedChange={toggleNotifications}
                    />
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Dashboard</CardTitle>
                  <CardDescription>
                    Configure dashboard display options
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium text-foreground">Auto-refresh Queue</p>
                      <p className="text-sm text-muted-foreground">
                        Automatically update queue data
                      </p>
                    </div>
                    <Switch checked={true} disabled />
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </SidebarInset>
      <Toaster position="top-right" />
    </SidebarProvider>
  );
}
