import { useEffect, useState } from "react";
import type { Run } from "./contracts";
import { automationApi } from "./api";
import { RunPlayback } from "./RunPlayback";
export function AgentRunMonitor({ agentId }: { agentId: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        if (!document.hidden) {
          const value = await automationApi.latestAgentRun(agentId);
          if (!stopped) {
            setRun(value);
            setError("");
          }
        }
      } catch {
        if (!stopped) setError("无法刷新桌面运行画面");
      }
      if (!stopped) timer = setTimeout(poll, 2000);
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [agentId]);
  if (!run) return null;
  return (
    <details
      className="auto-agent-monitor"
      open={run.status === "running" ? true : undefined}
    >
      <summary>
        桌面试运行 · {run.status === "running" ? "执行中" : "查看回放"}
      </summary>
      {error && <p role="status">{error}</p>}
      <RunPlayback key={run.id} run={run} />
      <a
        href={`/automations?workflow=${run.workflow_id}`}
        target="_blank"
        rel="noreferrer"
      >
        查看流程
      </a>
    </details>
  );
}
