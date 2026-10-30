import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { automationApi } from "./api";
import type {
  AssignmentAgent,
  AssignmentPage,
  AssignmentResult,
} from "./contracts";
import "./assignments.css";

interface Props {
  workflowId: string;
  workflowName: string;
  version: { id: string; number: number };
  published: boolean;
  onClose: () => void;
}

export function ToolAssignmentDialog({
  workflowId,
  workflowName,
  version,
  published,
  onClose,
}: Props) {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<AssignmentPage | null>(null);
  const [selected, setSelected] = useState<AssignmentAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<AssignmentResult | null>(null);

  useEffect(() => {
    let stopped = false;
    const timer = setTimeout(() => {
      void automationApi
        .assignmentCandidates(workflowId, version.id, search, offset)
        .then((value) => {
          if (!stopped) {
            setPage(value);
            setLoading(false);
          }
        })
        .catch((e: unknown) => {
          if (!stopped) {
            setError(e instanceof Error ? e.message : "读取员工失败");
            setLoading(false);
          }
        });
    }, 200);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [workflowId, version.id, search, offset, refresh]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [busy, onClose]);

  const eligible = page?.items.filter((a) => !a.assigned) || [];
  const allSelected =
    eligible.length > 0 &&
    eligible.every((a) => selected.some((s) => s.id === a.id));
  const handleToggle = (agent: AssignmentAgent) => {
    setError("");
    if (selected.some((a) => a.id === agent.id))
      setSelected(selected.filter((a) => a.id !== agent.id));
    else if (selected.length < 100) setSelected([...selected, agent]);
    else setError("单次最多选择 100 名员工，请分批分配。");
  };
  const handleSelectPage = () => {
    if (allSelected)
      setSelected(selected.filter((a) => !eligible.some((e) => e.id === a.id)));
    else {
      const next = [
        ...selected,
        ...eligible.filter((a) => !selected.some((s) => s.id === a.id)),
      ];
      if (next.length > 100) {
        setError("单次最多选择 100 名员工，请分批分配。");
        return;
      }
      setSelected(next);
    }
  };
  const handleAssign = async () => {
    setBusy(true);
    setError("");
    try {
      const value = await automationApi.assign(
        workflowId,
        version.id,
        selected.map((a) => a.id),
      );
      setResult(value);
      setSelected([]);
      setLoading(true);
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "分配失败，请刷新员工状态后重试。",
      );
    } finally {
      setBusy(false);
    }
  };
  const handleReload = () => {
    setError("");
    setLoading(true);
    setRefresh((n) => n + 1);
  };
  return (
    <div
      className="auto-modal-backdrop"
      onClick={() => {
        if (!busy) onClose();
      }}
    >
      <section
        className="auto-modal auto-assignment-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="assignment-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="auto-row">
          <h2 id="assignment-title">
            {published ? "Tool 已发布，分配给员工" : "分配 Tool 给员工"}
          </h2>
          <span className="auto-spacer" />
          <button
            className="btn btn-secondary"
            aria-label="关闭分配引导"
            disabled={busy}
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className="auto-assignment-steps">
          <span className="done">✓ 已发布 Tool</span>
          <span className={result ? "done" : ""}>
            {result ? "✓ 已分配员工" : "2 选择员工"}
          </span>
          <span className={result ? "done" : ""}>
            {result ? "✓ 已启用使用" : "3 启用使用"}
          </span>
        </div>
        <strong>
          {workflowName} · v{version.number}
        </strong>
        <p className="auto-hint">
          一个 Tool
          可供多个员工使用。可现在批量分配，也可稍后从版本历史进入。完整配置仍在各员工的
          Tool 中管理。
        </p>
        {result && (
          <div className="auto-notice" role="status">
            已为 {result.assigned_count} 名员工启用 v{version.number}。
            {result.unchanged_count > 0 &&
              `其中 ${result.unchanged_count} 名原本已绑定此版本。`}
            <div className="auto-assignment-results">
              {result.agents.map((a) => (
                <Link
                  key={a.id}
                  to={`/agents/${a.id}`}
                >
                  {a.name}
                </Link>
              ))}
            </div>
          </div>
        )}
        <input
          autoFocus
          aria-label="搜索可分配员工"
          placeholder="搜索有权限管理的员工"
          value={search}
          disabled={busy}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
            setLoading(true);
            setError("");
          }}
        />
        <div className="auto-row auto-assignment-tools">
          <button
            className="btn btn-secondary"
            disabled={loading || busy || !eligible.length}
            onClick={handleSelectPage}
          >
            {allSelected ? "取消选择当前页" : "全选当前页"}
          </button>
          <span>本次选择 {selected.length}/100 名</span>
          <span className="auto-spacer" />
          <button
            className="btn btn-secondary"
            disabled={!selected.length || busy}
            onClick={() => setSelected([])}
          >
            清空选择
          </button>
        </div>
        {error && (
          <div className="auto-error" role="alert">
            {error}{" "}
            <button
              className="btn btn-secondary"
              disabled={busy}
              onClick={handleReload}
            >
              刷新员工状态
            </button>
          </div>
        )}
        <div className="auto-assignment-list" aria-busy={loading}>
          {loading ? (
            <p className="auto-hint">正在读取员工及绑定状态…</p>
          ) : !page?.items.length ? (
            <p className="auto-hint">
              {search
                ? "没有匹配的可管理员工，试试其他名称。"
                : "暂无可分配的员工，请先创建员工或取得配置权限。"}
            </p>
          ) : (
            page.items.map((a) => (
              <label key={a.id} className="auto-assignment-agent">
                <input
                  type="checkbox"
                  aria-label={`选择员工 ${a.name}`}
                  disabled={busy || a.assigned}
                  checked={a.assigned || selected.some((s) => s.id === a.id)}
                  onChange={() => handleToggle(a)}
                />
                <span>{a.name}</span>
                <small>
                  {a.assigned
                    ? `已绑定 v${version.number}`
                    : a.versions.length
                      ? `当前 v${a.versions.map((v) => v.number).join(" / v")}，选择后切换至 v${version.number}`
                      : "尚未分配"}
                </small>
              </label>
            ))
          )}
        </div>
        <div className="auto-row auto-assignment-pagination">
          <span className="auto-hint">共 {page?.total || 0} 名可管理员工</span>
          <span className="auto-spacer" />
          <button
            className="btn btn-secondary"
            disabled={busy || loading || offset === 0}
            onClick={() => {
              setOffset(Math.max(0, offset - 50));
              setLoading(true);
            }}
          >
            上一页
          </button>
          <button
            className="btn btn-secondary"
            disabled={busy || loading || page?.next_offset == null}
            onClick={() => {
              if (page?.next_offset != null) {
                setOffset(page.next_offset);
                setLoading(true);
              }
            }}
          >
            下一页
          </button>
        </div>
        <p className="auto-hint">
          只修改勾选员工的本流程版本。未勾选员工和其他 Tool
          保持原设置；以后发布新版，也不会自动升级已有绑定。
        </p>
        <div className="auto-row">
          <button
            className="btn btn-secondary"
            disabled={busy}
            onClick={onClose}
          >
            {published && !result ? "稍后分配" : "完成"}
          </button>
          <span className="auto-spacer" />
          <button
            className="btn btn-primary"
            disabled={busy || loading || !selected.length}
            onClick={() => void handleAssign()}
          >
            {busy ? "正在批量分配…" : `为 ${selected.length} 名员工启用 Tool`}
          </button>
        </div>
      </section>
    </div>
  );
}
