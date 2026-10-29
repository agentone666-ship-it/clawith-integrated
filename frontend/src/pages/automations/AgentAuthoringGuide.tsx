import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { copyToClipboard } from "../../utils/clipboard";
import { automationApi } from "./api";
import type { AuthoringReadiness, Workflow } from "./contracts";
import "./authoring.css";

interface Props {
  workflow: Workflow | null;
  onClose: () => void;
}
export function AgentAuthoringGuide({ workflow, onClose }: Props) {
  const navigate = useNavigate();
  const [page, setPage] = useState<AuthoringReadiness | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    let disposed = false;
    void automationApi
      .authoring("", 0)
      .then((value) => {
        if (!disposed) setPage(value);
      })
      .catch((e: unknown) => {
        if (!disposed)
          setError(e instanceof Error ? e.message : "无法加载规范，请重试。");
      });
    return () => {
      disposed = true;
    };
  }, []);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && panel.current) {
        const items = Array.from(
          panel.current.querySelectorAll<HTMLElement>(
            "button:not(:disabled),summary",
          ),
        );
        const first = items[0],
          last = items[items.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === panel.current)
        ) {
          e.preventDefault();
          last?.focus();
        } else if (
          !e.shiftKey &&
          (document.activeElement === last ||
            document.activeElement === panel.current)
        ) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [onClose]);
  const ready = page?.items.filter((a) => a.ready) || [];
  const agent = ready.find((a) => a.name.includes("脚本工程师")) || ready[0];
  const handleStart = () => {
    if (!page || !agent) return;
    const text =
      "我想把这项经常重复的工作交给你：\n【请填写】\n描述时可以参考：在哪个系统里操作、平时要做哪些事、最后希望得到什么结果。比如：在采购系统里查找申请单，核对供应商和金额，然后保存采购草稿。\n请帮我做成以后能重复使用的流程，先验证结果，再告诉我怎么用；缺少必要信息时再问我。";
    navigate(`/agents/${agent.id}/chat`, {
      state: {
        composerHandoff: {
          agentId: agent.id,
          text,
          document: {
            name: "AUTOMATION_AGENT.md",
            text:
              page.spec_markdown +
              (workflow
                ? `\n\n## 可只读参考的流程\n${workflow.id}（${workflow.name}）。新建流程，不得覆盖参考流程。`
                : ""),
          },
          createdAt: Date.now(),
        },
      },
    });
  };
  const handleCopy = async () => {
    if (!page) return;
    if (await copyToClipboard(page.spec_markdown)) {
      setCopied(true);
      setError("");
    } else setError("复制失败，请展开规范后手动复制。");
  };
  return (
    <div className="auto-modal-backdrop" onClick={onClose}>
      <section
        ref={panel}
        tabIndex={-1}
        className="auto-modal auto-authoring-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="authoring-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="auto-authoring-heading">
          <h2 id="authoring-title">编写脚本</h2>
          <button className="btn btn-ghost" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </div>
        <p className="auto-authoring-lead">
          规范会自动带入 Agent 聊天。到聊天里描述需求，Agent
          负责编写、提交和验证。
        </p>
        {error && (
          <p className="auto-error" role="alert">
            {error}
          </p>
        )}
        {!page && !error && (
          <p className="auto-hint" role="status">
            正在加载规范…
          </p>
        )}
        {page && !agent && (
          <p className="auto-hint">
            暂无已接入的脚本员工，可复制规范交给已有 coding agent。
          </p>
        )}
        {copied && (
          <p className="auto-hint" role="status">
            规范已复制
          </p>
        )}
        <details className="auto-authoring-details">
          <summary>查看规范</summary>
          <pre>{page?.spec_markdown || "正在加载…"}</pre>
        </details>
        <div className="auto-authoring-footer">
          <button
            className="btn btn-secondary"
            disabled={!page}
            onClick={() => void handleCopy()}
          >
            复制规范
          </button>
          <button
            className="btn btn-primary"
            disabled={!agent}
            onClick={handleStart}
          >
            开始编写
          </button>
        </div>
      </section>
    </div>
  );
}
