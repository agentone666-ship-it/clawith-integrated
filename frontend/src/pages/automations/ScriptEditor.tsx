import { useState } from "react";
import { actionLabels, newStep, reconcileParameters } from "./contracts";
import type { RpaScript, Step } from "./contracts";
interface Props {
  script: RpaScript;
  onChange: (script: RpaScript) => void;
  onSave: () => void;
  busy: boolean;
}
export function ScriptEditor({ script, onChange, onSave, busy }: Props) {
  const [advanced, setAdvanced] = useState(false);
  const [json, setJson] = useState("");
  const [error, setError] = useState("");
  const update = (id: string, changes: Partial<Step>) =>
    onChange(
      reconcileParameters({
        ...script,
        steps: script.steps.map((s) =>
          s.id === id ? { ...s, ...changes } : s,
        ),
      }),
    );
  const move = (index: number, delta: number) => {
    const steps = [...script.steps];
    const other = index + delta;
    if (other < 0 || other >= steps.length) return;
    [steps[index], steps[other]] = [steps[other], steps[index]];
    onChange({ ...script, steps });
  };
  return (
    <section className="auto-editor">
      <div className="auto-toolbar">
        <strong>
          {script.steps.length} 个步骤 · {Object.keys(script.parameters).length}{" "}
          个参数
        </strong>
        <span className="auto-spacer" />
        <button
          className="btn btn-secondary"
          onClick={() => {
            setAdvanced(!advanced);
            setJson(JSON.stringify(script, null, 2));
            setError("");
          }}
        >
          {advanced ? "返回步骤视图" : "高级脚本"}
        </button>
        <button className="btn btn-primary" disabled={busy} onClick={onSave}>
          保存草稿
        </button>
      </div>
      <p className="auto-hint">
        文本中的 <code>{"${parameter_name}"}</code>{" "}
        会成为调用参数。窗口内坐标可以随窗口位置移动；窗口标题也可使用参数。布局改变时应重新验证。
      </p>
      {advanced ? (
        <div className="auto-card">
          <textarea
            className="auto-source"
            aria-label="自动化脚本 JSON"
            value={json}
            onChange={(e) => setJson(e.target.value)}
          />
          <button
            className="btn btn-secondary"
            onClick={() => {
              try {
                const parsed: RpaScript = JSON.parse(json) as RpaScript;
                if (
                  parsed.format !== "clawith.cua.v1" ||
                  !Array.isArray(parsed.steps)
                )
                  throw new Error("脚本格式不正确");
                onChange(reconcileParameters(parsed));
                setAdvanced(false);
              } catch (e) {
                setError(e instanceof Error ? e.message : "JSON 无效");
              }
            }}
          >
            应用脚本修改
          </button>
          {error && <p className="auto-error">{error}</p>}
        </div>
      ) : (
        <div className="auto-steps">
          {!script.steps.length && (
            <div className="auto-empty">
              还没有步骤。先到“录制工作台”录制操作。
            </div>
          )}
          {script.steps.map((step, i) => (
            <article className="auto-step" key={step.id}>
              <div className="auto-step-header">
                <span className="auto-step-number">{i + 1}</span>
                <strong>{actionLabels[step.action]}</strong>
                <input
                  aria-label={`步骤${i + 1}说明`}
                  value={step.label}
                  onChange={(e) => update(step.id, { label: e.target.value })}
                  placeholder="步骤说明"
                />
                <button
                  className="auto-icon-btn"
                  title="上移"
                  onClick={() => move(i, -1)}
                >
                  ↑
                </button>
                <button
                  className="auto-icon-btn"
                  title="下移"
                  onClick={() => move(i, 1)}
                >
                  ↓
                </button>
                <button
                  className="auto-icon-btn"
                  title="删除步骤"
                  onClick={() =>
                    onChange(
                      reconcileParameters({
                        ...script,
                        steps: script.steps.filter((s) => s.id !== step.id),
                      }),
                    )
                  }
                >
                  ×
                </button>
              </div>
              {step.target && (
                <div className="auto-target">
                  <span>{step.target.app}</span>
                  <input
                    aria-label={`步骤${i + 1}窗口标题`}
                    value={step.target.title}
                    onChange={(e) =>
                      update(step.id, {
                        target: { ...step.target!, title: e.target.value },
                      })
                    }
                  />
                </div>
              )}
              {(step.action === "type_text" ||
                step.action === "assert_text") && (
                <textarea
                  aria-label={`步骤${i + 1}文本`}
                  value={step.text}
                  onChange={(e) => update(step.id, { text: e.target.value })}
                />
              )}
              {step.x !== null && step.y !== null && (
                <div className="auto-row">
                  <label>
                    窗口内 X{" "}
                    <input
                      type="number"
                      value={step.x}
                      onChange={(e) =>
                        update(step.id, { x: Number(e.target.value) })
                      }
                    />
                  </label>
                  <label>
                    Y{" "}
                    <input
                      type="number"
                      value={step.y}
                      onChange={(e) =>
                        update(step.id, { y: Number(e.target.value) })
                      }
                    />
                  </label>
                </div>
              )}
              {(step.action === "press_key" || step.action === "hotkey") && (
                <code>{[...step.modifiers, step.key].join(" + ")}</code>
              )}
              {step.action === "launch_app" && <code>{step.app}</code>}
            </article>
          ))}
          <button
            className="btn btn-secondary"
            onClick={() => {
              const target = [...script.steps]
                .reverse()
                .find((s) => s.target)?.target;
              if (!target) {
                setError("先录制一个目标窗口，再添加验证。");
                return;
              }
              onChange({
                ...script,
                steps: [
                  ...script.steps,
                  newStep("assert_text", {
                    target,
                    text: "请输入期望出现的结果",
                    label: "验证业务结果",
                  }),
                ],
              });
            }}
          >
            ＋ 添加结果验证
          </button>
          {error && <p className="auto-error">{error}</p>}
        </div>
      )}
      {!!Object.keys(script.parameters).length && (
        <div className="auto-card">
          <h3>调用参数</h3>
          {Object.entries(script.parameters).map(([key, description]) => (
            <div className="auto-row" key={key}>
              <code>{key}</code>
              <input
                aria-label={`${key}参数说明`}
                value={description}
                onChange={(e) =>
                  onChange({
                    ...script,
                    parameters: { ...script.parameters, [key]: e.target.value },
                  })
                }
              />
              <label>
                <input
                  type="checkbox"
                  checked={script.secret_parameters.includes(key)}
                  onChange={(e) =>
                    onChange({
                      ...script,
                      secret_parameters: e.target.checked
                        ? [...script.secret_parameters, key]
                        : script.secret_parameters.filter((x) => x !== key),
                    })
                  }
                />
                敏感值
              </label>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
