import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { fetchJson } from '../../services/api';
import { useAuthStore } from '../../stores';
import { studioApi } from './api';
import { emptySpecification, invalidateReviews } from './contracts';
import type { Blueprint, EmployeeSpecification, Readiness } from './contracts';
import { SpecificationEditor } from './SpecificationEditor';
import { TestCaseEditor } from './TestCaseEditor';
import { jobTemplates } from './templates';
import './studio.css';

interface AvailableModel { id: string; label: string; enabled: boolean }
const fieldLabels: Record<string, string> = {
    name: '员工名称', audience: '服务对象', objective: '工作目标', responsibilities: '岗位职责',
    boundaries: '禁止事项', output_format: '输出格式', acceptance_criteria: '验收标准',
    test_cases: '测试用例', connections: '业务接入需求',
};

export function EmployeeStudio() {
    const user = useAuthStore(state => state.user);
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const scope = [user?.tenant_id, user?.id];
    const [offset, setOffset] = useState(0);
    const [blueprint, setBlueprint] = useState<Blueprint | null>(null);
    const [spec, setSpec] = useState<EmployeeSpecification>(emptySpecification);
    const [requirement, setRequirement] = useState('');
    const [modelId, setModelId] = useState('');
    const [busy, setBusy] = useState('');
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [dirty, setDirty] = useState(false);
    const [readiness, setReadiness] = useState<Readiness | null>(null);
    const published = !!blueprint?.published_at;
    const drafts = useQuery({ queryKey: ['employee-blueprints', ...scope, offset], queryFn: () => studioApi.list(offset) });
    const catalog = useQuery({ queryKey: ['employee-capabilities', ...scope], queryFn: studioApi.catalog });
    const models = useQuery({
        queryKey: ['studio-models', ...scope],
        queryFn: () => fetchJson<AvailableModel[]>('/enterprise/llm-models'),
    });
    useEffect(() => {
        function beforeUnload(event: BeforeUnloadEvent) {
            if (dirty) { event.preventDefault(); event.returnValue = ''; }
        }
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty]);

    function edit(value: EmployeeSpecification) {
        setSpec(value); setDirty(true); setReadiness(null); setMessage('');
    }
    function open(row: Blueprint | null) {
        if (dirty && !window.confirm('当前修改尚未保存，是否放弃？')) return;
        setBlueprint(row); setRequirement(row?.requirement ?? '');
        setSpec(row?.specification ?? emptySpecification());
        setDirty(false); setReadiness(null); setError(''); setMessage('');
    }
    async function perform(label: string, action: () => Promise<void>) {
        setBusy(label); setError(''); setMessage('');
        try { await action(); }
        catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败，请重试'); }
        finally { setBusy(''); }
    }
    async function save() {
        const normalized = { ...spec };
        for (const key of ['responsibilities', 'boundaries', 'acceptance_criteria'] as const) {
            normalized[key] = spec[key].map(item => item.trim()).filter(Boolean);
        }
        const saved = await studioApi.save(blueprint, requirement, normalized);
        setBlueprint(saved); setSpec(saved.specification); setDirty(false); setReadiness(null);
        await queryClient.invalidateQueries({ queryKey: ['employee-blueprints', ...scope] });
        return saved;
    }
    async function check() {
        const saved = dirty || !blueprint ? await save() : blueprint;
        const result = await studioApi.check(saved.id);
        setReadiness(result);
        setMessage(result.ready ? '岗位配置检查通过。尚未进行真实业务试运行。' : '请完成下列检查项后重试。');
    }
    async function create() {
        if (!blueprint || dirty || !modelId) return;
        const agent = await studioApi.create(blueprint, modelId);
        await queryClient.invalidateQueries({ queryKey: ['agents'] });
        await queryClient.invalidateQueries({ queryKey: ['employee-blueprints', ...scope] });
        navigate(`/agents/${agent.id}/chat`);
    }

    return <main className="employee-studio">
        <header className="studio-row"><div><p className="studio-kicker">数字员工 · 开发工作台</p>
            <h1>把岗位需求变成可执行的员工</h1>
            <p className="studio-muted">定义岗位 → 选择能力 → 审阅用例 → 创建员工 → 试运行</p></div>
            <Link className="btn btn-secondary" to="/dashboard">返回工作台</Link>
        </header>
        <div className="studio-layout">
            <aside className="studio-sidebar">
                <button className="btn btn-primary" disabled={!!busy} onClick={() => open(null)}>新建岗位草稿</button>
                <h3>我的岗位草稿</h3>
                {drafts.isPending && <p role="status">正在加载草稿…</p>}
                {drafts.isError && <p role="alert">草稿加载失败。<button className="btn btn-ghost" onClick={() => drafts.refetch()}>重试</button></p>}
                {drafts.data?.length === 0 && <p className="studio-muted">保存后可在这里继续编辑。</p>}
                {drafts.data?.map(row => <button disabled={!!busy} key={row.id}
                    className={`studio-draft ${blueprint?.id === row.id ? 'selected' : ''}`} onClick={() => open(row)}>
                    <strong>{row.specification.name || '未命名岗位'}</strong>
                    <span>{row.published_at ? '已创建 · 岗位快照' : `草稿 · 第 ${row.revision} 版`}</span>
                </button>)}
                <div className="studio-row"><button className="btn btn-ghost" disabled={!!busy || offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</button>
                    <button className="btn btn-ghost" disabled={!!busy || (drafts.data?.length ?? 0) < 30}
                        onClick={() => setOffset(offset + 30)}>下一页</button></div>
            </aside>
            <div className="studio-content">
                {error && <p className="studio-error" role="alert">{error}</p>}
                {message && <p role="status">{message}</p>}
                {published && <p>此配置已作为创建快照保存。<Link to={`/agents/${blueprint?.published_agent_id}/chat`}>打开员工并试运行</Link></p>}
                <fieldset disabled={!!busy || published}>
                    <section className="studio-panel studio-form">
                        <h2>1. 描述岗位</h2>
                        <label>选择模型<select className="form-input" value={modelId} onChange={e => setModelId(e.target.value)}>
                            <option value="">请选择模型</option>
                            {models.data?.filter(model => model.enabled).map(model => <option key={model.id} value={model.id}>{model.label}</option>)}
                        </select></label>
                        {models.isError && <p role="alert">模型加载失败，请刷新页面或联系管理员。</p>}
                        {!models.isPending && !models.isError && !models.data?.some(model => model.enabled)
                            && <p className="studio-muted">暂无可用模型，请联系管理员配置；仍可手动编辑和保存草稿。</p>}
                        <label>希望数字员工承担什么工作？<textarea className="form-textarea" rows={4}
                            placeholder="例如：为供应链团队跟踪订单交期异常，输出证据和建议，修改订单前需要人工确认。"
                            maxLength={6000} value={requirement} onChange={e => {
                                setRequirement(e.target.value); edit(invalidateReviews(spec));
                            }} /></label>
                        <div className="studio-row"><button type="button" className="btn btn-primary"
                            disabled={!modelId || requirement.trim().length < 5}
                            onClick={() => perform('生成岗位配置', async () => {
                                edit(await studioApi.generate(requirement, spec.employee_kind, modelId));
                                setMessage('已生成初始配置，请核对岗位信息、补齐能力并审阅测试用例。');
                            })}>用模型生成配置</button>
                            <span className="studio-muted">也可以手动填写或使用模板</span></div>
                        <div className="studio-row">{jobTemplates.map(template => <button type="button"
                            className="btn btn-secondary" key={template.label} onClick={() => {
                                if (dirty && !window.confirm('使用模板会替换当前未保存的内容，是否继续？')) return;
                                setRequirement(template.requirement); edit(structuredClone(template.specification));
                            }}>{template.label}</button>)}</div>
                    </section>
                    <section className="studio-panel"><h2>2. 配置岗位和能力</h2>
                        {catalog.isError && <p role="alert">能力列表加载失败，请刷新后再选择；已选能力将在创建时重新校验。</p>}
                        <SpecificationEditor value={spec} catalog={catalog.data} onChange={edit} />
                    </section>
                    <section className="studio-panel"><h2>3. 确认测试用例</h2>
                        <p className="studio-muted">修改岗位或用例后，请先保存，再逐项确认。已保存的内容变更会清除之前的确认记录。</p>
                        <TestCaseEditor value={spec.test_cases} onChange={test_cases => edit({ ...spec, test_cases })} />
                    </section>
                    <section className="studio-panel"><h2>4. 检查并创建</h2>
                        <p className="studio-muted">创建后进入现有员工工作区。工具凭证、触发器和真实业务试运行在员工页配置；本页不会自动执行测试或接通老系统。</p>
                        <div className="studio-row">
                            <button className="btn btn-secondary" type="button" onClick={() => perform('保存草稿', async () => {
                                await save(); setMessage('草稿已保存。若修改了内容，请重新确认测试用例。');
                            })}>保存草稿{dirty ? ' · 有修改' : ''}</button>
                            <button className="btn btn-secondary" type="button" onClick={() => perform('检查配置', check)}>检查配置</button>
                            <button className="btn btn-primary" type="button" disabled={!readiness?.ready || dirty || !modelId}
                                onClick={() => perform('创建员工', create)}>创建员工并打开工作区</button>
                        </div>
                        {readiness && <div className="studio-checks" aria-live="polite">
                            {readiness.issues.map((issue, index) => <p key={index} className="studio-error">{fieldLabels[issue.field] ?? issue.field}：{issue.message}</p>)}
                            {readiness.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
                        </div>}
                    </section>
                </fieldset>
                {busy && <p role="status" aria-live="polite">{busy}中，请稍候…</p>}
            </div>
        </div>
    </main>;
}
