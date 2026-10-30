import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PublicationConfirm } from "./PublicationConfirm";
import type { AgentDesktopActivity } from "./contracts";
import { automationApi } from "./api";
import { ComputerPreview } from "./ComputerPreview";
import { RunPlayback } from "./RunPlayback";
export function AgentRunMonitor({
  agentId,
  sessionId,
}: {
  agentId: string;
  sessionId?: string;
}) {
  const [activity, setActivity] = useState<AgentDesktopActivity | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!sessionId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        if (!document.hidden) {
          const value = await automationApi.agentActivity(agentId, sessionId);
          if (!stopped) {
            setActivity(value);
            setError("");
          }
        }
      } catch {
        if (!stopped) setError("无法刷新桌面运行状态，请稍后重试");
      }
      if (!stopped) timer = setTimeout(poll, 1000);
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [agentId, sessionId]);
  if (!sessionId || activity?.session_id !== sessionId)
    return error ? <p role="alert">{error}</p> : null;
  const run = activity.playback;
  return (
    <section className="auto-agent-monitor" aria-label="本次桌面任务">
      {error && <p role="alert">{error}</p>}
      <div>
        <strong>本次桌面任务</strong> · 已调用 {activity.tool_calls} 个工具
      </div>
      {!run && activity.computer ? (
        <ComputerPreview
          key={activity.agent_run_id}
          runId={activity.agent_run_id}
          active={activity.lane_held}
        />
      ) : !run ? (
        <p role="status">
          {activity.lane_held
            ? "任务处理中，尚未进入桌面试运行。"
            : activity.tool_calls === 0
              ? "本次未调用工具，也未启动桌面试运行，因此没有新的操作画面。"
              : "本次尚未启动桌面试运行，没有新的操作画面。"}
        </p>
      ) : (
        <>
          <RunPlayback key={run.id} run={run} />
          {!activity.lane_held && run.status === "succeeded" && (
            <PublicationConfirm key={run.id} run={run} />
          )}
          <Link to={`/automations?workflow=${run.workflow_id}&tab=runs`}>
            查看流程与诊断
          </Link>
        </>
      )}
    </section>
  );
}
