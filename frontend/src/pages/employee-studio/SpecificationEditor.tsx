import { connectionKinds, employeeKinds, invalidateReviews } from './contracts';
import type { CapabilityCatalog, ConnectionKind, EmployeeKind, EmployeeSpecification } from './contracts';

interface SpecificationEditorProps {
    value: EmployeeSpecification;
    catalog?: CapabilityCatalog;
    onChange: (value: EmployeeSpecification) => void;
}

export function SpecificationEditor({ value, catalog, onChange }: SpecificationEditorProps) {
    const update = (patch: Partial<EmployeeSpecification>) => onChange(invalidateReviews({ ...value, ...patch }));
    const textFields = [
        ['name', '员工名称', 100], ['audience', '服务对象', 500],
        ['objective', '工作目标', 3000], ['output_format', '输出格式', 3000],
    ] as const;
    const listFields = [
        ['responsibilities', '岗位职责'], ['boundaries', '禁止事项与确认规则'], ['acceptance_criteria', '业务验收标准'],
    ] as const;
    return <div className="studio-form">
        <label>员工类型<select className="form-input" value={value.employee_kind}
            onChange={e => update({ employee_kind: e.target.value as EmployeeKind })}>
            {Object.entries(employeeKinds).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        <p className="studio-muted">类型用于描述岗位；本版创建后仅本人可用，部门和分公司数据权限需另行配置。</p>
        {textFields.map(([key, label, max]) => <label key={key}>{label}
            <textarea className="form-textarea" rows={key === 'name' || key === 'audience' ? 1 : 3}
                maxLength={max} value={value[key]} onChange={e => update({ [key]: e.target.value })} />
        </label>)}
        {listFields.map(([key, label]) => <label key={key}>{label}（每行一项，最多 12 项）
            <textarea className="form-textarea" rows={3} value={value[key].join('\n')}
                onChange={e => update({ [key]: e.target.value.split('\n') })} />
        </label>)}
        <h3>业务接入需求</h3>
        <p className="studio-muted">记录接入方式不会自动连接系统。实际可调用能力请在下方选择或创建后配置。</p>
        {(Object.entries(connectionKinds) as [ConnectionKind, string][]).map(([kind, label]) => {
            const selected = value.connections.find(item => item.kind === kind);
            return <div key={kind}><label className="studio-choice"><input type="checkbox" checked={!!selected}
                onChange={e => update({ connections: e.target.checked
                    ? [...value.connections, { kind, description: '' }]
                    : value.connections.filter(item => item.kind !== kind) })} />{label}</label>
                {selected && <label>系统与操作说明<input className="form-input" maxLength={500} value={selected.description}
                    onChange={e => update({ connections: value.connections.map(item => item.kind === kind
                        ? { ...item, description: e.target.value } : item) })} /></label>}
            </div>;
        })}
        {(['skills', 'tools'] as const).map(category => {
            const key = category === 'skills' ? 'skill_ids' : 'tool_ids';
            return <label key={category}>{category === 'skills' ? '关联 Skill' : '关联已注册工具'}（最多 20 项）
                <select className="form-input studio-capabilities" multiple value={value[key]}
                    onChange={e => update({ [key]: Array.from(e.target.selectedOptions, item => item.value) })}>
                    {(catalog?.[category] ?? []).map(item => <option value={item.id} key={item.id} title={item.description}>{item.name}</option>)}
                </select>
            </label>;
        })}
        <p className="studio-muted">按住 Ctrl / Command 多选。能力列表最多展示 200 项；凭证及权限仍需在工具中配置。</p>
    </div>;
}
