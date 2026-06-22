"use client";
import { ReasoningLog } from "./ReasoningLog";
import { useLiveQueue } from "@/hooks/useLiveQueue";

export function ReasoningLogClient() {
  const { queueEvents } = useLiveQueue();
  return <ReasoningLog entries={queueEvents} />;
}

export default ReasoningLogClient;
