import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import "./cloud-desktops.css";
import { request } from "../../api/request";

interface CloudDesktop {
  id: string;
  agent_id: string | null;
  agent_name: string;
  state:
    | "stopped"
    | "starting"
    | "restoring"
    | "ready"
    | "saving"
    | "saved"
    | "error";
  busy: boolean;
  vcpus: number;
  memory_mib: number;
  auto_save_after_seconds: number;
  last_error: string;
}

const labels: Record<CloudDesktop["state"], string> = {
  stopped: "尚未启动",
  starting: "启动中",
  restoring: "恢复中",
  ready: "待机",
  saving: "保存状态中",
  saved: "已休眠 · 计算资源已释放",
  error: "需要检查",
};

interface Props {
  onRecordingCreated: (id: string) => Promise<void>;
}

export function CloudDesktops({ onRecordingCreated }: Props) {
  const [rows, setRows] = useState<CloudDesktop[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let disposed = false;
    const load = async () => {
      try {
        const value = await request<CloudDesktop[]>("/automations/desktops");
        if (!disposed) {
          setRows(value);
          setError("");
        }
      } catch (e) {
        if (!disposed)
          setError(e instanceof Error ? e.message : "无法读取云电脑");
      } finally {
        if (!disposed) setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);
  const handleRecord = async (id: string) => {
    setBusy(id);
    setError("");
    try {
      const workflow = await request<{ id: string }>(
        `/automations/desktops/${id}/recording-workflow`,
        { method: "POST" },
      );
      await onRecordingCreated(workflow.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法新建录制");
    } finally {
      setBusy("");
    }
  };
  const handleAction = async (id: string, action: "start" | "save") => {
    setBusy(id);
    setError("");
    try {
      await request<CloudDesktop>(`/automations/desktops/${id}/${action}`, {
        method: "POST",
      });
      setRows(await request<CloudDesktop[]>("/automations/desktops"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "云电脑操作失败");
    } finally {
      setBusy("");
    }
  };
  return (
    <section className="auto-card" aria-label="我的云电脑">
      <div className="auto-cloud-header">
        <div>
          <h2>我的云电脑</h2>
          <p className="auto-muted">
            每位员工使用独立的 Windows
            环境，归属当前账号。登录态、软件和文件持续保留；任务结束后自动保存状态并释放计算资源。
          </p>
        </div>
      </div>
      {error && (
        <div className="auto-error-banner" role="alert">
          {error}
        </div>
      )}
      {loading ? (
        <p role="status">正在读取云电脑…</p>
      ) : rows.length === 0 ? (
        <div className="auto-empty">
          <h3>使用时自动创建</h3>
          <p>
            给员工启用云电脑工具后，直接在聊天中安排任务。首次调用会创建专属环境，无需提前配置虚拟机。
          </p>
        </div>
      ) : (
        <div style={{ display: "grid", gap: 12 }}>
          {rows.map((row) => (
            <article key={row.id} className="auto-card">
              <div className="auto-cloud-header">
                <div>
                  <h3>{row.agent_name}</h3>
                  <p className="auto-muted">
                    {row.busy
                      ? "任务使用中"
                      : labels[row.state] || "状态待确认"}{" "}
                    · {row.vcpus} 核 / {row.memory_mib / 1024} GB · 持久环境
                  </p>
                  {row.last_error && <p role="alert">{row.last_error}</p>}
                </div>
                <div className="auto-row" style={{ flexWrap: "wrap" }}>
                  <button
                    className="btn btn-secondary"
                    disabled={!!busy || row.busy}
                    onClick={() => void handleRecord(row.id)}
                  >
                    录制流程
                  </button>
                  {row.agent_id && (
                    <Link
                      className="btn btn-secondary"
                      to={`/agents/${row.agent_id}/chat`}
                    >
                      去聊天
                    </Link>
                  )}
                  {["stopped", "saved", "error"].includes(row.state) && (
                    <button
                      className="btn btn-secondary"
                      disabled={!!busy || row.busy}
                      onClick={() => void handleAction(row.id, "start")}
                    >
                      {busy === row.id
                        ? "处理中…"
                        : row.state === "saved"
                          ? "恢复"
                          : "启动"}
                    </button>
                  )}
                  {["ready", "error"].includes(row.state) && (
                    <button
                      className="btn btn-secondary"
                      disabled={!!busy || row.busy}
                      onClick={() => void handleAction(row.id, "save")}
                    >
                      {busy === row.id ? "处理中…" : "休眠"}
                    </button>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
