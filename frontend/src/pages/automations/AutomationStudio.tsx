import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { automationApi } from "./api";
import type { Recording, Script, Workflow, WorkflowSummary } from "./contracts";
import { RecordingPanel } from "./RecordingPanel";
import { ScriptEditor } from "./ScriptEditor";
import { RunPanel } from "./RunPanel";
import { VersionPanel } from "./VersionPanel";
import "./studio.css";

type Tab = "record" | "edit" | "runs" | "versions";
const tabs: { id: Tab; label: string }[] = [
  { id: "record", label: "录制工作台" },
  { id: "edit", label: "步骤与参数" },
  { id: "runs", label: "试运行与记录" },
  { id: "versions", label: "版本与 Tool" },
];

export function AutomationStudio() {
  const [query, setQuery] = useSearchParams();
  const [selected, setSelected] = useState(query.get("workflow") || "");
  const selectedRef = useRef(selected);
  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const [list, setList] = useState<WorkflowSummary[]>([]);
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [script, setScript] = useState<Script | null>(null);
  const [tab, setTab] = useState<Tab>("record");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState("");
  const onError = useCallback((message: string) => setError(message), []);
  const refreshList = useCallback(async () => {
    const rows = await automationApi.list();
    setList(rows);
    setSelected((previous) => previous || rows[0]?.id || "");
  }, []);
  const refresh = useCallback(async () => {
    if (!selected) return;
    const value = await automationApi.detail(selected);
    if (selectedRef.current === selected) setWorkflow(value);
  }, [selected]);
  useEffect(() => {
    let disposed = false;
    void automationApi
      .list()
      .then((rows) => {
        if (!disposed) {
          setList(rows);
          setSelected((previous) => previous || rows[0]?.id || "");
        }
      })
      .catch((e) => {
        if (!disposed)
          onError(e instanceof Error ? e.message : "无法读取流程库");
      });
    return () => {
      disposed = true;
    };
  }, [onError]);
  useEffect(() => {
    if (!selected) return;
    let stopped = false;
    void automationApi
      .detail(selected)
      .then((w) => {
        if (!stopped) {
          setWorkflow(w);
          setScript(w.draft);
        }
      })
      .catch((e) => {
        if (!stopped) onError(e instanceof Error ? e.message : "读取失败");
      });
    return () => {
      stopped = true;
    };
  }, [selected, onError]);
  const reloadDraft = useCallback(async () => {
    if (!selected) return;
    const value = await automationApi.detail(selected);
    if (selectedRef.current === selected) {
      setWorkflow(value);
      setScript(value.draft);
    }
    await refreshList();
  }, [selected, refreshList]);
  const recorded = useCallback(async () => {
    await reloadDraft();
    setTab("edit");
  }, [reloadDraft]);
  const onRecording = useCallback(
    (recording: Recording | null) =>
      setWorkflow((previous) =>
        previous ? { ...previous, recording } : previous,
      ),
    [],
  );
  const handleCreate = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const w = await automationApi.create(name.trim(), description.trim());
      setSelected(w.id);
      setQuery({ workflow: w.id });
      setCreating(false);
      setName("");
      setDescription("");
      setTab("record");
      await refreshList();
    } catch (e) {
      onError(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  };
  const handleSave = async () => {
    if (!workflow || !script) return;
    setBusy(true);
    setError("");
    try {
      const w = await automationApi.save(workflow, script);
      setWorkflow(w);
      setScript(w.draft);
      setNotice("草稿已保存，可换数据试运行。");
      await refreshList();
    } catch (e) {
      onError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };
  const dirty =
    !!workflow &&
    !!script &&
    JSON.stringify(script) !== JSON.stringify(workflow.draft);
  return (
    <div className="auto-shell">
      <header className="auto-page-header">
        <div>
          <span className="auto-eyebrow">AUTOMATION STUDIO</span>
          <h1>桌面自动化</h1>
          <p>把一次人工操作，变成数字员工可调用的流程。</p>
        </div>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          ＋ 新建自动化
        </button>
      </header>
      {error && (
        <div className="auto-error-banner" role="alert">
          {error}
          <button aria-label="关闭错误提示" onClick={() => setError("")}>
            ×
          </button>
        </div>
      )}
      {notice && (
        <div className="auto-notice" role="status">
          {notice}
          <button aria-label="关闭提示" onClick={() => setNotice("")}>
            ×
          </button>
        </div>
      )}
      <div className="auto-workspace">
        <aside className="auto-library">
          <div className="auto-library-title">
            <strong>流程库</strong>
            <span>{list.length}</span>
          </div>
          <input
            aria-label="搜索自动化流程"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索流程名称"
          />
          {!list.length && (
            <p className="auto-hint">创建第一个流程，从独立桌面开始录制。</p>
          )}
          {list
            .filter((w) => (w.name + w.description).includes(search))
            .map((w) => (
              <button
                className={
                  "auto-library-item " + (selected === w.id ? "selected" : "")
                }
                key={w.id}
                onClick={() => {
                  setSelected(w.id);
                  setQuery({ workflow: w.id });
                  setNotice("");
                }}
              >
                <span className="auto-library-icon">▣</span>
                <div>
                  <strong>{w.name}</strong>
                  <small>{w.description || "桌面流程"}</small>
                  <small>草稿 r{w.revision}</small>
                </div>
              </button>
            ))}
        </aside>
        <main className="auto-main">
          {workflow && script && workflow.id === selected ? (
            <>
              <div className="auto-workflow-heading">
                <div>
                  <h2>{workflow.name}</h2>
                  <p>
                    {workflow.description ||
                      "录制、验证、发布并交给数字员工执行。"}
                  </p>
                </div>
                <span className="auto-badge">草稿 r{workflow.revision}</span>
              </div>
              <nav className="auto-tabs" aria-label="自动化管理栏目">
                {tabs.map((t) => (
                  <button
                    key={t.id}
                    className={tab === t.id ? "active" : ""}
                    onClick={() => setTab(t.id)}
                    disabled={
                      (!!workflow.recording && t.id !== "record") ||
                      (dirty && (t.id === "runs" || t.id === "versions"))
                    }
                  >
                    {t.label}
                  </button>
                ))}
              </nav>
              {dirty && (
                <p className="auto-notice">
                  步骤有未保存的修改。请先保存草稿，再试运行或发布。
                </p>
              )}
              {tab === "record" && (
                <RecordingPanel
                  key={workflow.recording?.id || "idle"}
                  workflow={workflow}
                  recording={workflow.recording}
                  onRecording={onRecording}
                  onSaved={recorded}
                  onError={onError}
                />
              )}
              {tab === "edit" && (
                <ScriptEditor
                  script={script}
                  onChange={setScript}
                  onSave={() => void handleSave()}
                  busy={busy}
                />
              )}
              {tab === "runs" && (
                <RunPanel
                  workflowId={workflow.id}
                  script={script}
                  runs={workflow.runs}
                  onChanged={refresh}
                  onError={onError}
                />
              )}
              {tab === "versions" && (
                <VersionPanel
                  workflow={workflow}
                  onChanged={reloadDraft}
                  onError={onError}
                />
              )}
            </>
          ) : (
            <div className="auto-welcome">
              <span>▣</span>
              <h2>{selected ? "正在加载流程…" : "录下一次，重复执行"}</h2>
              <p>
                支持 Windows 桌面点击、输入和快捷键。
                <br />
                设置参数与成功条件，验证后发布为 Agent Tool。
              </p>
              {!selected && (
                <button
                  className="btn btn-primary"
                  onClick={() => setCreating(true)}
                >
                  创建第一个自动化
                </button>
              )}
            </div>
          )}
        </main>
      </div>
      {creating && (
        <div className="auto-modal-backdrop" onClick={() => setCreating(false)}>
          <section
            className="auto-modal"
            role="dialog"
            aria-modal="true"
            aria-label="新建自动化"
            onClick={(e) => e.stopPropagation()}
          >
            <h2>新建自动化</h2>
            <label>
              流程名称
              <input
                aria-label="流程名称"
                autoFocus
                value={name}
                maxLength={120}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：创建采购草稿"
              />
            </label>
            <label>
              业务说明
              <textarea
                aria-label="业务说明"
                value={description}
                maxLength={1000}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="告诉数字员工这个流程适合什么任务"
              />
            </label>
            <div className="auto-row">
              <span className="auto-spacer" />
              <button className="btn" onClick={() => setCreating(false)}>
                取消
              </button>
              <button
                className="btn btn-primary"
                disabled={busy || !name.trim()}
                onClick={() => void handleCreate()}
              >
                创建并录制
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
