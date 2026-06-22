import { createContext, useContext } from "react";
import { useLiveQueue } from "@/hooks/useLiveQueue";

type LiveQueueStore = ReturnType<typeof useLiveQueue>;

const LiveQueueContext = createContext<LiveQueueStore | null>(null);

export function LiveQueueProvider({ children }: { children: React.ReactNode }) {
  const store = useLiveQueue();
  return <LiveQueueContext.Provider value={store}>{children}</LiveQueueContext.Provider>;
}

export function useSharedLiveQueue() {
  const context = useContext(LiveQueueContext);
  if (!context) {
    throw new Error("useSharedLiveQueue must be used inside LiveQueueProvider");
  }
  return context;
}
