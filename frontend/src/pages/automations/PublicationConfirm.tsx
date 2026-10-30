import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Run, Workflow } from "./contracts";
import { automationApi } from "./api";
export function PublicationConfirm({ run }: { run: Run }) {
  const navigate = useNavigate();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    void automationApi
      .detail(run.workflow_id)
      .then((w) => {
        if (!stopped) setWorkflow(w);
      })
      .catch(() => {
        if (!stopped) setError("无法读取脚本，请稍后重试");
      });
    return () => {
      stopped = true;
    };
  }, [run.workflow_id]);
  const published = workflow?.versions.some((v) => v.digest === run.digest);
  const confirm = async () => {
    if (!workflow || busy) return;
    setBusy(true);
    setError("");
    try {
      await automationApi.publish(
        workflow,
        "用户在 Agent 聊天确认发布",
        run.digest,
      );
      navigate(`/automations?workflow=${run.workflow_id}&tab=versions`);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "发布失败，请检查当前代码与试运行结果",
      );
      setBusy(false);
    }
  };
  return (
    <div className="auto-card" aria-label="脚本交付确认">
      <strong>{published ? "脚本已发布" : "脚本已保存并验证"}</strong>
      <p>{workflow?.name || "正在读取脚本…"}</p>
      {error && <p role="alert">{error}</p>}
      {published ? (
        <Link
          className="btn btn-secondary"
          to={`/automations?workflow=${run.workflow_id}&tab=versions`}
        >
          查看版本
        </Link>
      ) : (
        <>
          <p className="auto-hint">
            确认后发布为 Tool，可供其他 Agent 按需绑定。
          </p>
          <button
            className="btn btn-primary"
            disabled={!workflow || busy}
            onClick={() => void confirm()}
          >
            {busy ? "发布中…" : "确认发布"}
          </button>
        </>
      )}
    </div>
  );
}
