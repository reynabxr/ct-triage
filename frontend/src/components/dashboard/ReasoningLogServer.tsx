import { ReasoningLog } from "./ReasoningLog";
import type { QueueEventRecord } from "@/lib/queue-models";

export function ReasoningLogServer({ entries }: { entries: QueueEventRecord[] }) {
  return <ReasoningLog entries={entries} />;
}

export default ReasoningLogServer;
