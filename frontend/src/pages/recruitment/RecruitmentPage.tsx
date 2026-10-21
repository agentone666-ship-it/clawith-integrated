import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { IconArrowLeft, IconArrowUp, IconBriefcase, IconCheck, IconFileText, IconMessageCircle, IconPlus, IconSettings, IconUser } from '@tabler/icons-react';
import { agentApi, enterpriseApi, tenantApi } from '../../services/api';
import { recruitmentApi } from '../../services/recruitmentApi';
import MarkdownRenderer from '../../components/MarkdownRenderer';
import { useAuthStore } from '../../stores';
import { ResumePanel } from './ResumePanel';
import { InterviewPanel } from './InterviewPanel';
import type { Dossier, InterviewTask, Model, Resume } from './types';
import './recruitment.css';

const WELCOME = '你好，我是你的招聘 HR。你想找一位什么样的数字员工？告诉我希望他帮你完成的工作，我来梳理岗位、匹配能力，再安排面试。';
const EXAMPLES = [
    ['销售助理', '我想招一个销售助理，帮我整理销售数据、发现异常，再给我一份简洁的日报。'],
    ['内容运营', '我需要一个内容运营，帮我把产品资料整理成公众号文章，发布前先交给我审核。'],
    ['研究助理', '我想招一个研究助理，根据我提供的资料提炼结论，并保留每条结论的来源。'],
];

export function RecruitmentPage() {
    const { dossierId } = useParams();
    const [search] = useSearchParams();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const user = useAuthStore(s => s.user);
    const [composer, setComposer] = useState(() => search.get('role') ? `我想招聘：${search.get('role')}` : '');
    const [sourceRole, setSourceRole] = useState(search.get('role'));
    const [modelId, setModelId] = useState('');
    const [busy, setBusy] = useState('');
    const [error, setError] = useState('');
    const [rightTab, setRightTab] = useState<'resume' | 'interview'>('resume');
    const [selectedInterview, setSelectedInterview] = useState<string | null>(null);
    const chatEnd = useRef<HTMLDivElement>(null);
    const input = useRef<HTMLTextAreaElement>(null);
    const dossierQuery = useQuery({
        queryKey: ['recruitment', dossierId], queryFn: () => recruitmentApi.get(dossierId!), enabled: !!dossierId,
    });
    const row = dossierQuery.data;
    const drafts = useQuery({ queryKey: ['recruitment-list'], queryFn: recruitmentApi.list });
    const modelQuery = useQuery({ queryKey: ['llm-models'], queryFn: () => enterpriseApi.llmModels() as Promise<Model[]> });
    const models = (modelQuery.data || []).filter(model => model.enabled);
    const tenantQuery = useQuery({ queryKey: ['tenant', 'me'], queryFn: () => tenantApi.me() });
    const preferredModel = models.find(m => m.id === tenantQuery.data?.default_model_id)?.id || models[0]?.id || '';
    const effectiveModel = models.some(m => m.id === modelId) ? modelId : preferredModel;
    const catalog = useQuery({ queryKey: ['recruitment-catalog'], queryFn: recruitmentApi.catalog });
    const candidate = useQuery({
        queryKey: ['recruitment-candidate', row?.candidate_id],
        queryFn: () => agentApi.get(row!.candidate_id!) as Promise<{ status: string }>,
        enabled: !!row?.candidate_id,
        refetchInterval: query => query.state.data?.status === 'creating' ? 1500 : false,
    });
    const preparing = !!row?.candidate_id && (candidate.isPending || candidate.data?.status === 'creating');
    const candidateError = row?.candidate_id ? candidate.error : null;
    const messages = row?.messages || [{ role: 'assistant', content: WELCOME }];
    const canConfigure = user?.role === 'platform_admin' || user?.role === 'org_admin';

    if (sourceRole !== search.get('role')) {
        setSourceRole(search.get('role'));
        if (search.get('role')) setComposer(`我想招聘：${search.get('role')}`);
    }

    useEffect(() => { chatEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [row?.revision, busy]);

    function accept(next: Dossier) {
        queryClient.setQueryData(['recruitment', next.id], next);
        void queryClient.invalidateQueries({ queryKey: ['recruitment-list'] });
        if (dossierId !== next.id) navigate(`/recruitment/${next.id}`, { replace: true });
    }

    async function perform(label: string, operation: () => Promise<Dossier>) {
        if (busy) return null;
        setBusy(label);
        setError('');
        try {
            const next = await operation();
            accept(next);
            return next;
        } catch (err) {
            setError(err instanceof Error ? err.message : '操作未完成，请重试');
            return null;
        } finally { setBusy(''); }
    }

    async function handleSend(text = composer) {
        if (!text.trim() || !effectiveModel) return;
        const result = await perform('HR 正在梳理岗位、匹配能力…', async () => {
            const current = row || await recruitmentApi.create();
            if (!row) accept(current);
            return recruitmentApi.talk(current, text.trim(), effectiveModel);
        });
        if (result) setComposer('');
    }

    async function handleAssemble() {
        if (!row || !row.resume) return;
        const result = await perform('HR 正在组装候选员工…', async () => {
            await agentApi.create({ name: row.resume!.name, primary_model_id: effectiveModel,
                recruitment_id: row.id, recruitment_revision: row.revision });
            void queryClient.invalidateQueries({ queryKey: ['agents'] });
            return recruitmentApi.get(row.id);
        });
        if (result) setRightTab('interview');
    }

    async function handleStart(task: InterviewTask) {
        if (!row) return;
        const requestId = crypto.randomUUID();
        const result = await perform('正在安排面试…', () => recruitmentApi.start(row, task, requestId));
        if (result) setSelectedInterview(requestId);
    }

    async function handleReview(id: string, decision: 'pass' | 'fail', feedback: string) {
        if (!row) return;
        await perform(decision === 'fail' ? 'HR 正在根据面评调整简历…' : '正在保存面评…', async () => {
            const reviewed = await recruitmentApi.review(row, id, decision, feedback);
            accept(reviewed);
            if (decision === 'pass') return reviewed;
            setRightTab('resume');
            try {
                return await recruitmentApi.talk(reviewed, '请根据刚才保存的不通过面评调整员工简历，说明调整了什么。保留已认可的能力，准备复试。', effectiveModel);
            } catch (err) {
                throw Object.assign(new Error(`面评已保存，HR 暂未完成调整：${err instanceof Error ? err.message : '请稍后重试'}`), { cause: err });
            }
        });
    }

    function handleNew() {
        navigate('/recruitment'); setComposer(''); setError(''); setSelectedInterview(null); setRightTab('resume');
    }

    return <div className="recruitment-page">
        <header className="recruit-header"><div><Link className="recruit-back" to="/dashboard"><IconArrowLeft size={14} />工作台</Link>
            <h1 className="page-title">招聘数字员工</h1><p>和 HR 聊聊，找到能把工作做好的新同事。</p></div>
            <div className="recruit-header-actions">
                <select aria-label="招聘记录" className="form-input" value={dossierId || ''} disabled={!!busy || !!drafts.error} onChange={e => {
                    setError(''); setComposer(''); setSelectedInterview(null); setRightTab('resume');
                    if (e.target.value) navigate(`/recruitment/${e.target.value}`); else handleNew();
                }}><option value="">{drafts.error ? '招聘记录加载失败' : '新的招聘'}</option>{drafts.data?.map(d => <option value={d.id} key={d.id}>{d.resume?.name || d.messages.find(m => m.role === 'user')?.content.slice(0, 20) || '招聘进行中'}{d.hired_at ? ' · 已录用' : ''}</option>)}</select>
                <button className="btn btn-secondary" onClick={handleNew} disabled={!!busy}><IconPlus size={15} />新招聘</button>
            </div>
        </header>
        <nav className="recruit-progress" aria-label="招聘进度">
            {[['聊需求', IconMessageCircle], ['确认简历', IconFileText], ['面试与面评', IconBriefcase], ['录用入职', IconCheck]].map(([text, Icon], index) => {
                const active = row?.hired_at ? 3 : row?.candidate_current ? 2 : row?.resume ? 1 : 0;
                const StepIcon = Icon as typeof IconCheck;
                return <div key={String(text)} className={index <= active ? 'is-active' : ''}><StepIcon size={15} stroke={1.7} /><span>{String(text)}</span>{index < 3 && <span className="recruit-progress-line" />}</div>;
            })}
        </nav>
        {(error || dossierQuery.error || modelQuery.error || candidateError) && <div className="recruit-error" role="alert">
            <span>{error || dossierQuery.error?.message || modelQuery.error?.message || candidateError?.message}</span>
            {dossierId && <button className="btn btn-secondary" disabled={!!busy} onClick={() => { setError(''); void dossierQuery.refetch(); if (row?.candidate_id) void candidate.refetch(); }}>刷新记录</button>}
        </div>}
        {!modelQuery.isPending && !modelQuery.error && models.length === 0 && <div className="recruit-notice" role="status">
            <IconSettings size={17} /><div><strong>HR 还缺少一个可用模型</strong><p>{canConfigure ? '配置企业模型后，就可以开始对话招聘和真实面试。' : '请联系管理员配置企业模型，然后回来开始招聘。'}</p></div>
            {canConfigure && <Link className="btn btn-secondary" to="/enterprise#llm">配置模型</Link>}
        </div>}
        <div className="recruit-workspace">
            <section className="recruit-chat" aria-label="与招聘 HR 对话">
                <div className="recruit-chat-heading"><div className="recruit-avatar">HR</div><div><strong>招聘顾问</strong><p>聊需求 · 选配能力 · 跟进面试</p></div><span className="recruit-badge">{row?.hired_at ? '已完成' : 'HR'}</span></div>
                <div className="recruit-conversation">
                    {dossierQuery.isPending && dossierId ? <p className="recruit-muted">正在读取招聘记录…</p> : messages.map((message, index) => <div className={`recruit-chat-message ${message.role}`} key={index}>
                        <span className="recruit-message-sender">{message.role === 'user' ? <><IconUser size={12} />你</> : 'HR 招聘顾问'}</span><MarkdownRenderer content={message.content} />
                    </div>)}
                    {messages.length === 1 && !dossierId && <div className="recruit-examples"><span>也可以从这些工作聊起</span>{EXAMPLES.map(([label, text]) => <button disabled={!!busy} key={label} onClick={() => { setComposer(text); input.current?.focus(); }}>{label}<IconPlus size={12} /></button>)}</div>}
                    {busy && <div className="recruit-busy" role="status"><i className="recruit-working-dot" />{busy}</div>}
                    <div ref={chatEnd} />
                </div>
                {row?.hired_at ? <div className="recruit-chat-composer"><p>招聘完成，员工已经可以开始工作。</p><Link className="btn btn-primary" to={`/agents/${row.candidate_id}/chat`}>和新同事聊聊</Link></div> : <form className="recruit-chat-composer" onSubmit={e => { e.preventDefault(); void handleSend(); }}>
                    <textarea ref={input} className="form-input" aria-label="告诉 HR 你的用人需求" value={composer} onChange={e => setComposer(e.target.value)} maxLength={6000} rows={3}
                        placeholder="说说你想招什么人，或者补充、修改岗位要求…" disabled={!!busy || (!!dossierId && !row)}
                        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void handleSend(); } }} />
                    <div className="recruit-composer-bottom"><span>Enter 发送 · Shift + Enter 换行</span><button aria-label="发送给 HR" className="btn btn-primary" disabled={!!busy || !composer.trim() || !effectiveModel || (!!dossierId && !row)}><IconArrowUp size={17} /></button></div>
                    {models.length > 0 && <details className="recruit-model"><summary>HR 模型 · {models.find(m => m.id === effectiveModel)?.label || models.find(m => m.id === effectiveModel)?.model}</summary>
                        <select className="form-input" aria-label="HR 模型" value={effectiveModel} disabled={!!busy} onChange={e => setModelId(e.target.value)}>{models.map(model => <option key={model.id} value={model.id}>{model.label || model.model}</option>)}</select></details>}
                </form>}
            </section>
            <section className="recruit-candidate" aria-label="候选员工">
                <div className="recruit-tabs" role="tablist" aria-label="候选员工资料"><button role="tab" aria-selected={rightTab === 'resume' || !row?.resume} onClick={() => setRightTab('resume')}><IconFileText size={15} />员工简历</button>
                    <button role="tab" aria-selected={rightTab === 'interview' && !!row?.resume} disabled={!row?.resume} onClick={() => setRightTab('interview')}><IconBriefcase size={15} />面试与面评{row?.interviews.length ? <span className="recruit-tab-count">{row.interviews.length}</span> : null}</button>
                    {row && <span className="recruit-saved">已保存 · 第 {row.revision} 版</span>}</div>
                <div className="recruit-candidate-body" role="tabpanel">
                    {rightTab === 'resume' || !row?.resume ? <ResumePanel row={row} catalog={catalog.data} busy={!!busy} assembled={!!row?.candidate_current}
                        canAssemble={!!effectiveModel}
                        retryAssembly={candidate.data?.status === 'error' || candidate.data?.status === 'stopped' || !!row?.interviews.some(i => i.candidate_id === row.candidate_id && i.decision === 'fail')}
                        onToggle={(resume: Resume) => { if (row) void perform('正在更新简历…', () => recruitmentApi.saveResume(row, resume)); }}
                        onAssemble={() => void handleAssemble()} onInterview={() => setRightTab('interview')}
                        onAdd={() => { setComposer('我还希望这位员工能够：'); input.current?.focus(); }} />
                        : <InterviewPanel row={row} busy={!!busy} preparing={preparing} selectedId={selectedInterview} onSelect={setSelectedInterview}
                            onStart={task => void handleStart(task)} onReview={(id, decision, feedback) => void handleReview(id, decision, feedback)}
                            onResume={() => setRightTab('resume')} onContinue={(id, content) => void perform('正在补充面试资料…', async () => {
                                const next = await recruitmentApi.continue(row, id, content);
                                void queryClient.invalidateQueries({ queryKey: ['recruitment-interview', row.id, id] }); return next;
                            })}
                            onCancel={id => void perform('正在申请结束面试…', async () => {
                                const next = await recruitmentApi.cancel(row, id);
                                void queryClient.invalidateQueries({ queryKey: ['recruitment-interview', row.id, id] }); return next;
                            })}
                            onHire={() => void perform('正在办理入职…', async () => {
                                const next = await recruitmentApi.hire(row); void queryClient.invalidateQueries({ queryKey: ['agents'] }); return next;
                            })} />}
                </div>
            </section>
        </div>
    </div>;
}
