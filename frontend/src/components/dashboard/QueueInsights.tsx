import {
  Area,
  AreaChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CalendarDays, AlertTriangle, Activity } from "lucide-react";
import {
  congestionForecast,
  demandForecast,
  deriveQueueCaseViewModel,
  type QueueCaseRecord,
} from "@/lib/queue-models";

export function QueueInsights({ queue }: { queue: QueueCaseRecord[] }) {
  const atRisk = queue
    .map((record) => ({ record, view: deriveQueueCaseViewModel(record) }))
    .filter(({ view }) => view.remainingMinutes !== null && view.remainingMinutes <= 25);

  return (
    <section id="insights" className="grid gap-4 lg:grid-cols-3">
      <InfoCard
        icon={<Activity className="h-3.5 w-3.5" />}
        title="Scanner capacity"
        accent="stable"
      >
        <div className="text-2xl font-semibold tracking-tight text-foreground">1/1</div>
        <p className="mt-1 text-xs text-muted-foreground">
          Single CT scanner online · operating at full capacity
        </p>
      </InfoCard>

      <InfoCard
        icon={<CalendarDays className="h-3.5 w-3.5" />}
        title="Calendar context"
        accent="info"
      >
        <div className="text-2xl font-semibold tracking-tight text-foreground">Weekday</div>
        <p className="mt-1 text-xs text-muted-foreground">
          No public holiday. Normal volume expected.
        </p>
      </InfoCard>

      <InfoCard
        icon={<AlertTriangle className="h-3.5 w-3.5" />}
        title="Patients over target"
        accent={atRisk.length > 0 ? "critical" : "stable"}
      >
        <div className="text-2xl font-semibold tracking-tight text-foreground">{atRisk.length}</div>
        <p className="mt-1 text-xs text-muted-foreground">Within 25 minutes of recommended time</p>
      </InfoCard>

      <ChartCard title="Expected incoming demand" subtitle="Orders per hour, next 7h">
        <ResponsiveContainer width="100%" height={140}>
          <AreaChart data={demandForecast} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
            <defs>
              <linearGradient id="demandFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="oklch(0.55 0.13 245)" stopOpacity={0.32} />
                <stop offset="100%" stopColor="oklch(0.55 0.13 245)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="window"
              tick={{ fontSize: 10 }}
              stroke="oklch(0.7 0.02 250)"
              tickLine={false}
              axisLine={false}
              interval={0}
              tickMargin={8}
              padding={{ left: 8, right: 8 }}
            />
            <YAxis
              tick={{ fontSize: 11 }}
              stroke="oklch(0.7 0.02 250)"
              tickLine={false}
              axisLine={false}
              width={28}
            />
            <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: "oklch(0.85 0.02 245)" }} />
            <Area
              type="monotone"
              dataKey="demand"
              stroke="oklch(0.55 0.13 245)"
              strokeWidth={2}
              fill="url(#demandFill)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="Queue congestion forecast" subtitle="Projected queue size over next 60 min">
        <ResponsiveContainer width="100%" height={140}>
          <LineChart data={congestionForecast} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
            <XAxis
              dataKey="time"
              tick={{ fontSize: 11 }}
              stroke="oklch(0.7 0.02 250)"
              tickLine={false}
              axisLine={false}
              interval="preserveStartEnd"
              minTickGap={20}
              tickMargin={8}
              padding={{ left: 8, right: 8 }}
            />
            <YAxis
              tick={{ fontSize: 11 }}
              stroke="oklch(0.7 0.02 250)"
              tickLine={false}
              axisLine={false}
              width={28}
            />
            <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: "oklch(0.85 0.02 245)" }} />
            <Line
              type="monotone"
              dataKey="queue"
              stroke="oklch(0.65 0.13 195)"
              strokeWidth={2.2}
              dot={{ r: 2.5, fill: "oklch(0.65 0.13 195)", strokeWidth: 0 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="rounded-2xl border border-border bg-surface p-5 shadow-soft">
        <div className="flex items-center justify-between">
          <div>
            <h4 className="text-sm font-semibold tracking-tight text-foreground">
              Approaching target time
            </h4>
            <p className="text-xs text-muted-foreground">Within 25 minutes of recommended time</p>
          </div>
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-risk-critical-soft text-risk-critical">
            <AlertTriangle className="h-4 w-4" />
          </div>
        </div>
        <ul className="mt-3 space-y-1.5">
          {atRisk.length === 0 && (
            <li className="text-xs text-muted-foreground">No patients at risk right now.</li>
          )}
          {atRisk.slice(0, 5).map(({ record, view }) => {
            const remaining = view.remainingMinutes ?? 0;
            return (
              <li
                key={record.caseId}
                className="flex items-center justify-between rounded-lg border border-border/70 bg-surface-elevated/50 px-2.5 py-1.5"
              >
                <div className="min-w-0">
                  <div className="text-xs font-medium text-foreground">{view.displayName}</div>
                  <div className="truncate text-[11px] text-muted-foreground">{view.scanLabel}</div>
                </div>
                <div
                  className={`text-xs font-semibold tabular-nums ${
                    remaining <= 0
                      ? "text-risk-critical"
                      : remaining <= 10
                        ? "text-risk-critical"
                        : "text-risk-moderate-foreground"
                  }`}
                >
                  {remaining > 0 ? `${remaining}m left` : "over"}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

const tooltipStyle = {
  background: "oklch(1 0 0)",
  border: "1px solid oklch(0.92 0.008 240)",
  borderRadius: 10,
  fontSize: 12,
  boxShadow: "0 4px 16px oklch(0.2 0.04 240 / 0.08)",
} as const;

function InfoCard({
  icon,
  title,
  accent,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  accent: "stable" | "moderate" | "critical" | "info";
  children: React.ReactNode;
}) {
  const tone = {
    stable: "bg-risk-stable-soft text-risk-stable",
    moderate: "bg-risk-moderate-soft text-risk-moderate-foreground",
    critical: "bg-risk-critical-soft text-risk-critical",
    info: "bg-info-soft text-info",
  }[accent];
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-soft">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {title}
        </h4>
        <div className={`flex h-7 w-7 items-center justify-center rounded-lg ${tone}`}>{icon}</div>
      </div>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-soft">
      <div>
        <h4 className="text-sm font-semibold tracking-tight text-foreground">{title}</h4>
        <p className="text-xs text-muted-foreground">{subtitle}</p>
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}
