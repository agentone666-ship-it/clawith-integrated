import type { EmployeeTestCase } from './contracts';

interface TestCaseEditorProps {
    value: EmployeeTestCase[];
    onChange: (value: EmployeeTestCase[]) => void;
}

const labels = { normal: '正常任务', exception: '异常处理', boundary: '权限与边界' };

export function TestCaseEditor({ value, onChange }: TestCaseEditorProps) {
    function edit(index: number, patch: Partial<EmployeeTestCase>) {
        onChange(value.map((item, position) => ({ ...item, reviewed: false, ...(position === index ? patch : {}) })));
    }
    return <section className="studio-form">
        <h3>测试用例人工审阅</h3>
        <p className="studio-muted">每类至少一项。确认仅表示输入和预期符合业务要求；创建后请在真实授权环境中试运行。</p>
        {value.map((item, index) => <div className="studio-test" key={index}>
            <div className="studio-row"><strong>{labels[item.kind]}</strong>
                <button className="btn btn-ghost" type="button" onClick={() => onChange(value.filter((_, position) => position !== index))}>删除</button>
            </div>
            <label>测试输入<textarea className="form-textarea" rows={2} maxLength={3000} value={item.input}
                onChange={e => edit(index, { input: e.target.value })} /></label>
            <label>预期结果<textarea className="form-textarea" rows={2} maxLength={3000} value={item.expected}
                onChange={e => edit(index, { expected: e.target.value })} /></label>
            <label className="studio-choice"><input type="checkbox" checked={item.reviewed}
                onChange={e => onChange(value.map((test, position) => position === index
                    ? { ...test, reviewed: e.target.checked } : test))} />我已确认此用例的输入和预期</label>
        </div>)}
        <div className="studio-row">{(Object.keys(labels) as EmployeeTestCase['kind'][]).map(kind => <button
            className="btn btn-secondary" type="button" key={kind} disabled={value.length >= 9}
            onClick={() => onChange([...value, { kind, input: '', expected: '', reviewed: false }])}>添加{labels[kind]}</button>)}</div>
    </section>;
}
