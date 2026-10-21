import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { IconArrowRight, IconCheck, IconPlayerPlay, IconSend, IconX } from '@tabler/icons-react';
import MarkdownRenderer from '../../components/MarkdownRenderer';
import { recruitmentApi } from '../../services/recruitmentApi';
import type { Dossier, Interview, InterviewTask } from './types';

const STATUS: Record<string, string> = {
    created: '已接受任务', queued: '正在排队', running: '正在试做', completed: '试做完成', failed: '执行失败',
    cancelled: '面试已结束', waiting_user: '等待你补充信息', waiting_approval: '等待操作确认',
    waiting_external: '等待外部系统', waiting_agent: '等待协作员工',
};
const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

interface Props {
    row: Dossier;
    busy: boolean;
    preparing: boolean;
    selectedId: string | null;
    onSelect: (id: string) => void;
    onStart: (task: InterviewTask) => void;
    onReview: (id: string, decision: 'pass' | 'fail', feedback: string) => void;
    onContinue: (id: string, content: string) => void;
    onCancel: (id: string) => void;
    onHire: () => void;
    onResume: () => void;
}

export function InterviewPanel(props: Props) {
    const { row, busy, preparing, onStart } = props;
    const [task, setTask] = useState('');
    const selected = row.interviews.find(i => i.id === props.selectedId) || row.interviews[row.interviews.length - 1];
    return <div className="recruit-interview">
        <div className="recruit-section-title"><div><span className="recruit-eyebrow">现场面试</span><h2>让他实际做一做</h2></div>
            <span className="recruit-badge">{row.interviews.length} 场面试</span></div>
        <p className="recruit-muted">可以使用 HR 准备的任务，也可以直接出题。观察实际执行和交付，再给面评。</p>
        {(!row.candidate_current || preparing) && <div className="recruit-notice">
            {preparing ? '候选员工正在准备工作环境，请稍候。' : '请先确认最新简历并组装候选员工，再开始面试。'}
            {!preparing && <button className="btn btn-secondary" onClick={props.onResume}>查看简历</button>}
        </div>}
        {!row.hired_at && <>
            <h3 className="recruit-subtitle">HR 为你准备的面试任务</h3>
            <div className="recruit-task-list">{row.resume?.interview_tasks.map((item, index) => <div className="recruit-task" key={`${index}-${item.title}`}>
                <span className="recruit-task-number">{String(index + 1).padStart(2, '0')}</span><div><strong>{item.title}</strong><p>{item.instruction}</p>
                    <span className="recruit-muted">观察重点：{item.look_for}</span></div>
                <button className="btn btn-secondary" disabled={busy || preparing || !row.candidate_current} onClick={() => onStart(item)}><IconPlayerPlay size={14} />试做</button>
            </div>)}</div>
            <form className="recruit-custom-task" onSubmit={e => { e.preventDefault(); if (task.trim()) onStart({ title: task.trim().slice(0, 80), instruction: task.trim(), look_for: '根据实际执行过程和交付结果，判断是否符合你的要求。' }); }}>
                <label htmlFor="interview-task">我也出一道题</label>
                <textarea id="interview-task" className="form-input" value={task} onChange={e => setTask(e.target.value)} maxLength={6000} rows={3}
                    placeholder="直接告诉他要做什么，也可以把一段资料粘贴在这里…" disabled={busy} />
                <button className="btn btn-secondary" type="submit" disabled={busy || preparing || !row.candidate_current || !task.trim()}><IconSend size={14} />交给候选员工</button>
            </form>
        </>}
        {row.interviews.length > 0 && <div className="recruit-session-picker"><label htmlFor="interview-history">面试记录</label>
            <select id="interview-history" className="form-input" value={selected?.id || ''} onChange={e => props.onSelect(e.target.value)}>
                {[...row.interviews].reverse().map((i, index) => <option key={i.id} value={i.id}>{row.interviews.length - index}. {i.task.title} · {i.decision === 'pass' ? '通过' : i.decision === 'fail' ? '需改进' : '待面评'}{i.candidate_id !== row.candidate_id ? '（旧版本）' : ''}</option>)}
            </select></div>}
        {selected && <InterviewResult key={selected.id} {...props} interview={selected} />}
        <div className="recruit-hire-footer"><div><strong>{row.hired_at ? '欢迎新同事入职' : '面试满意，就让他加入'}</strong><p>录用后可直接工作。初次仅本人可用，分享与自动工作在员工设置中配置。</p></div>
            {row.hired_at ? <Link className="btn btn-primary" to={`/agents/${row.candidate_id}/chat`}>去工作<IconArrowRight size={14} /></Link>
                : <button className="btn btn-primary" disabled={busy || !row.can_hire} onClick={props.onHire}><IconCheck size={15} />录用这位员工</button>}
        </div>
    </div>;
}

function InterviewResult({ row, interview, busy, onReview, onContinue, onCancel }: Props & { interview: Interview }) {
    const [feedback, setFeedback] = useState(interview.feedback);
    const [supplement, setSupplement] = useState('');
    const query = useQuery({
        queryKey: ['recruitment-interview', row.id, interview.id],
        queryFn: () => recruitmentApi.detail(row.id, interview.id),
        refetchInterval: query => query.state.error ? false : TERMINAL.has(query.state.data?.status || '') ? false : 1800,
    });
    const data = query.data;
    const status = data?.status || '';
    const terminal = TERMINAL.has(status);
    const old = interview.candidate_id !== row.candidate_id;
    return <section className="recruit-result">
        <div className="recruit-section-title"><h3>{interview.task.title}</h3><span role="status" className={`recruit-badge ${status === 'completed' ? 'is-success' : ''}`}>
            {query.isPending ? '读取执行记录…' : STATUS[status] || '执行状态待核实'}</span></div>
        {query.error && <div className="recruit-error" role="alert">{query.error.message}<button className="btn btn-secondary" onClick={() => void query.refetch()}>重新读取</button></div>}
        {data?.waiting_reason && <p className="recruit-notice">{data.waiting_reason}</p>}
        {data?.tools.map(tool => <details className="recruit-tool-step" key={tool.id}>
            <summary><IconToolsLabel name={tool.name} /><span>{({ started: '执行中', succeeded: '已完成', failed: '失败', unknown: '结果待确认' } as Record<string, string>)[tool.status] || tool.status}</span></summary>
            <pre>{tool.summary || '执行尚未返回结果。'}</pre>
        </details>)}
        <div className="recruit-execution-messages" aria-live="polite">{data?.messages.map((message, index) => <div key={index} className={`recruit-execution-message ${message.role}`}>
            <span className="recruit-eyebrow">{message.role === 'user' ? '面试官' : row.resume?.name || '候选员工'}</span><MarkdownRenderer content={message.content} />
        </div>)}</div>
        {data?.summary && <div className="recruit-delivery"><h4>本次交付</h4><MarkdownRenderer content={data.summary} /></div>}
        {data?.error && <div role="alert" className="recruit-error">{data.error}</div>}
        {data?.truncated && <p className="recruit-muted">此处展示最近的部分记录，完整内容可在员工会话中查看。</p>}
        {!terminal && data && !query.error && <div className="recruit-running">
            {!status.startsWith('waiting') && <span><i className="recruit-working-dot" />候选员工正在处理，执行记录会自动更新。</span>}
            <button className="btn btn-ghost" disabled={busy} onClick={() => onCancel(interview.id)}>结束本场面试</button>
        </div>}
        {data?.can_continue && !row.hired_at && !old && <form className="recruit-supplement" onSubmit={e => { e.preventDefault(); if (supplement.trim()) onContinue(interview.id, supplement.trim()); }}>
            <textarea className="form-input" aria-label="补充面试资料" placeholder="补充资料或回答员工的问题…" value={supplement} maxLength={6000} onChange={e => setSupplement(e.target.value)} />
            <button className="btn btn-secondary" disabled={busy || !supplement.trim()}>补充并继续</button>
        </form>}
        {status.startsWith('waiting') && !data?.can_continue && <p className="recruit-muted">需要审批或核实外部操作时，请进入员工工作台处理，再回到这里查看结果。</p>}
        <Link className="recruit-native-link" to={`/agents/${interview.candidate_id}/chat`}>打开员工工作台，查看完整会话与文件 <IconArrowRight size={13} /></Link>
        {terminal && !row.hired_at && !old && <div className="recruit-review">
            <h3>这次表现怎么样？</h3><p className="recruit-muted">{interview.decision ? `已记录：${interview.decision === 'pass' ? '通过' : '不通过，待改进'}。你也可以更新面评。` : '由你判断是否符合岗位要求。面评会交给 HR，用于调整简历和能力。'}</p>
            <textarea className="form-input" aria-label="面评" value={feedback} onChange={e => setFeedback(e.target.value)} rows={3} maxLength={3000}
                placeholder="例如：结论有用，但请按门店汇总；涉及发消息时先让我确认。" disabled={busy} />
            <div className="recruit-review-actions"><button className="btn btn-secondary" disabled={busy || !feedback.trim()} onClick={() => onReview(interview.id, 'fail', feedback)}><IconX size={14} />不通过，让 HR 调整</button>
                <button className="btn btn-primary" disabled={busy || status !== 'completed'} onClick={() => onReview(interview.id, 'pass', feedback)}><IconCheck size={14} />通过</button></div>
        </div>}
    </section>;
}

function IconToolsLabel({ name }: { name: string }) {
    return <strong>↳ {name}</strong>;
}
