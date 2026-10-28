import "./code.css";
import type { PythonScript } from "./contracts";
interface Props {
  script: PythonScript;
  onChange: (value: PythonScript) => void;
  onSave: () => void;
  busy: boolean;
}
export function PythonEditor({ script, onChange, onSave, busy }: Props) {
  return (
    <section>
      <div className="auto-card">
        <div className="auto-row">
          <h3>Python 脚本</h3>
          <span className="auto-spacer" />
          <button className="btn btn-primary" disabled={busy} onClick={onSave}>
            保存草稿
          </button>
        </div>
        <p className="auto-hint">
          支持参数计算、循环和条件分支，通过 ui 编排桌面操作。必须包含
          ui.assert_text 结果校验。保存后到“试运行与记录”测试。
        </p>
        <textarea
          className="auto-code-editor"
          aria-label="Python 脚本源码"
          spellCheck={false}
          maxLength={96000}
          value={script.source}
          onChange={(e) => onChange({ ...script, source: e.target.value })}
        />
        <details>
          <summary>可用的桌面 SDK</summary>
          <pre>{`from automation import ui, inputs
w = ui.window("notepad.exe", "*Notepad*")
ui.launch("notepad")
ui.click(80, 120, target=w)
ui.type_text(inputs["text"], target=w)
ui.hotkey("ctrl", "s", target=w)
ui.key("tab", target=w)
ui.assert_text(inputs["text"], target=w, timeout_seconds=8)`}</pre>
          <p className="auto-hint">
            坐标相对目标窗口。代码先在隔离环境生成动作计划，再由桌面执行器执行；界面观察由管理
            Tool 的 observe
            完成。纯计算库：decimal、math、json、re、datetime、itertools、statistics。最多
            120 步；不支持文件、网络和进程访问。敏感参数只能直接传给
            ui.type_text。
          </p>
        </details>
      </div>
      <div className="auto-card">
        <div className="auto-row">
          <h3>输入参数</h3>
          <span className="auto-spacer" />
          <button
            className="btn"
            onClick={() => {
              let n = 1;
              while (`param${n}` in script.parameters) n++;
              onChange({
                ...script,
                parameters: { ...script.parameters, [`param${n}`]: "参数说明" },
              });
            }}
          >
            ＋ 添加参数
          </button>
        </div>
        {Object.entries(script.parameters).map(([key, label]) => (
          <div className="auto-row" key={key}>
            <input
              aria-label={`参数名 ${key}`}
              defaultValue={key}
              maxLength={40}
              onBlur={(e) => {
                const name = e.target.value.trim();
                if (name === key) return;
                if (
                  !/^[a-zA-Z][a-zA-Z0-9_]{0,39}$/.test(name) ||
                  name in script.parameters
                ) {
                  e.target.value = key;
                  return;
                }
                const parameters = Object.fromEntries(
                  Object.entries(script.parameters).map(([k, v]) => [
                    k === key ? name : k,
                    v,
                  ]),
                );
                onChange({
                  ...script,
                  parameters,
                  secret_parameters: script.secret_parameters.map((k) =>
                    k === key ? name : k,
                  ),
                });
              }}
            />
            <input
              aria-label={`参数说明 ${key}`}
              value={label}
              maxLength={120}
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
                      : script.secret_parameters.filter((s) => s !== key),
                  })
                }
              />
              敏感
            </label>
            <button
              className="btn"
              onClick={() => {
                const parameters = { ...script.parameters };
                delete parameters[key];
                onChange({
                  ...script,
                  parameters,
                  secret_parameters: script.secret_parameters.filter(
                    (s) => s !== key,
                  ),
                });
              }}
            >
              删除
            </button>
          </div>
        ))}
        <p className="auto-hint">
          Agent 可通过管理 Tool
          声明有业务含义的参数名。源码和参数定义一起参与版本校验，修改后需要重新测试。
        </p>
      </div>
    </section>
  );
}
