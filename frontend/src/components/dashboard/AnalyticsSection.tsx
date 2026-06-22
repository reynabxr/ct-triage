import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { complianceTrend, throughputByHour } from "@/lib/queue-models";
import { Clock, Target, Activity, ShieldCheck, Cpu } from "lucide-react";

const formatThroughputHourTick = (value: string) => {
  const hour = Number.parseInt(value, 10);
  if (Number.isNaN(hour)) return value;
  const normalized = hour % 24;
  const suffix = normalized >= 12 ? "pm" : "am";
  const twelveHour = normalized % 12 === 0 ? 12 : normalized % 12;
  return `${twelveHour}${suffix}`;
};

const tooltipStyle = {
  background: "oklch(1 0 0)",
  border: "1px solid oklch(0.92 0.008 240)",
  borderRadius: 10,
  fontSize: 12,
  boxShadow: "0 4px 16px oklch(0.2 0.04 240 / 0.08)",
} as const;

export function AnalyticsSection() {
  return (
    <section id="analytics" className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h3 className="text-sm font-semibold tracking-tight text-foreground">
            Operational analytics
          </h3>
          <p className="text-xs text-muted-foreground">Last 7 days · auto-refreshes hourly</p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <Kpi
          icon={<Clock className="h-3.5 w-3.5" />}
          label="Avg waiting"
          value="34m"
          delta="-6m from last average"
          tone="stable"
        />
        <Kpi
          icon={<Target className="h-3.5 w-3.5" />}
          label="HIGH compliance"
          value="96%"
          delta="+2% from last average"
          tone="stable"
        />
        <Kpi
          icon={<ShieldCheck className="h-3.5 w-3.5" />}
          label="MEDIUM compliance"
          value="89%"
          delta="+4% from last average"
          tone="stable"
        />
        <Kpi
          icon={<Activity className="h-3.5 w-3.5" />}
          label="Throughput"
          value="57"
          delta="scans/day"
          tone="info"
        />
        <Kpi
          icon={<Cpu className="h-3.5 w-3.5" />}
          label="Scanner utilisation"
          value="78%"
          delta="optimal"
          tone="info"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-border bg-surface p-5 shadow-soft">
          <div className="mb-3 flex items-baseline justify-between">
            <div>
              <h4 className="text-sm font-semibold tracking-tight text-foreground">
                Target compliance trend
              </h4>
              <p className="text-xs text-muted-foreground">HIGH vs MEDIUM compliance, last 7 days</p>
            </div>
            <div className="flex gap-3 text-[11px] text-muted-foreground">
              <Legend dot="oklch(0.55 0.13 245)" label="HIGH" />
              <Legend dot="oklch(0.65 0.13 195)" label="MEDIUM" />
            </div>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={complianceTrend} margin={{ left: 0, right: 8 }}>
              <CartesianGrid
                stroke="oklch(0.94 0.008 240)"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey="day"
                tick={{ fontSize: 11 }}
                stroke="oklch(0.7 0.02 250)"
                tickLine={false}
                axisLine={false}
                interval="preserveStartEnd"
                minTickGap={16}
                tickMargin={8}
                padding={{ left: 8, right: 8 }}
              />
              <YAxis
                domain={[70, 100]}
                tick={{ fontSize: 11 }}
                stroke="oklch(0.7 0.02 250)"
                tickLine={false}
                axisLine={false}
                width={28}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Line
                type="monotone"
                dataKey="high"
                stroke="oklch(0.55 0.13 245)"
                strokeWidth={2.2}
                dot={{ r: 2.5, strokeWidth: 0, fill: "oklch(0.55 0.13 245)" }}
              />
              <Line
                type="monotone"
                dataKey="medium"
                stroke="oklch(0.65 0.13 195)"
                strokeWidth={2.2}
                dot={{ r: 2.5, strokeWidth: 0, fill: "oklch(0.65 0.13 195)" }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-2xl border border-border bg-surface p-5 shadow-soft">
          <div className="mb-3">
            <h4 className="text-sm font-semibold tracking-tight text-foreground">
              Throughput by hour
            </h4>
            <p className="text-xs text-muted-foreground">Scans completed today</p>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={throughputByHour} margin={{ left: 0, right: 8 }}>
              <CartesianGrid
                stroke="oklch(0.94 0.008 240)"
                strokeDasharray="3 3"
                vertical={false}
              />
              <XAxis
                dataKey="hour"
                tick={{ fontSize: 10 }}
                tickFormatter={formatThroughputHourTick}
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
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "oklch(0.96 0.01 240)" }} />
              <Bar dataKey="scans" fill="oklch(0.55 0.13 245)" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}

function Kpi({
  icon,
  label,
  value,
  delta,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  delta: string;
  tone: "stable" | "moderate" | "info";
}) {
  const toneClass = {
    stable: "bg-risk-stable-soft text-risk-stable",
    moderate: "bg-risk-moderate-soft text-risk-moderate-foreground",
    info: "bg-info-soft text-info",
  }[tone];
  return (
    <div className="rounded-2xl border border-border bg-surface p-4 shadow-soft transition-shadow hover:shadow-elevated">
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
        <span className={`flex h-6 w-6 items-center justify-center rounded-md ${toneClass}`}>
          {icon}
        </span>
      </div>
      <div className="mt-1.5 text-2xl font-semibold tracking-tight text-foreground tabular-nums">
        {value}
      </div>
      <div className="text-[11px] text-muted-foreground">{delta}</div>
    </div>
  );
}

function Legend({ dot, label }: { dot: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="h-2 w-2 rounded-full" style={{ background: dot }} />
      {label}
    </span>
  );
}
