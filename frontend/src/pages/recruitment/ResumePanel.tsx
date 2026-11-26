import { IconArrowRight, IconBriefcase, IconCheck, IconFileText, IconLock, IconRobot, IconTools } from '@tabler/icons-react';
import type { Catalog, Dossier, Resume } from './types';
import { SCOPE_LABELS } from './types';

interface Props {
    row?: Dossier;
    catalog?: Catalog;
    busy: boolean;
    assembled: boolean;
    retryAssembly: boolean;
    canAssemble: boolean;
    onToggle: (resume: Resume) => void;
    onAssemble: () => void;
    onInterview: () => void;
    onAdd: () => void;
}

export function ResumePanel({ row, catalog, busy, assembled, retryAssembly, canAssemble, onToggle, onAssemble, onInterview, onAdd }: Props) {
    const resume = row?.resume;
    if (!resume) return <div className="recruit-empty">
        <div className="recruit-empty-icon"><IconFileText size={32} stroke={1.2} /></div>
        <h2>下一位同事，从你的需求开始</h2>
        <p>告诉 HR 你需要什么帮助。岗位梳理、技能选配和面试安排，交给 HR。</p>
        <div className="recruit-empty-steps">
            {['聊聊工作需求', '确认员工简历', '现场面试，满意再录用'].map((text, index) =>
                <div key={text}><span>{index + 1}</span>{text}</div>)}
        </div>
        <span className="recruit-muted">员工简历将在这里生成</span>
    </div>;

    const resources = new Map([...(catalog?.skills || []), ...(catalog?.tools || [])].map(r => [r.id, r.name]));
    const count = resume.capabilities.filter(c => c.selected).length;
    return <div className="recruit-resume">
        <div className="recruit-resume-heading">
            <div className="recruit-avatar recruit-candidate-avatar"><IconRobot size={25} stroke={1.5} /></div>
            <div><span className="recruit-eyebrow">候选员工简历</span><h2>{resume.name}</h2><p>{resume.role}</p></div>
            <span className="recruit-badge">{row?.hired_at ? '已录用' : assembled ? '已组装 · 待面试' : '待确认'}</span>
        </div>
        <div className="recruit-resume-meta"><span><IconBriefcase size={14} />{SCOPE_LABELS[resume.scope]}</span><span>服务于 {resume.audience}</span></div>
        <section className="recruit-section"><h3>工作目标</h3><p>{resume.goal}</p></section>
        <section className="recruit-section">
            <div className="recruit-section-title"><h3>工作能力 <span className="recruit-muted">{count} 项已选</span></h3>
                <button className="btn btn-ghost" disabled={busy || !!row?.hired_at} onClick={onAdd}>＋ 添加要求</button></div>
            <div className="recruit-capabilities">{resume.capabilities.map(capability => <label className={`recruit-capability ${capability.selected ? 'is-selected' : ''}`} key={capability.key}>
                <input type="checkbox" checked={capability.selected} disabled={busy || !!row?.hired_at}
                    onChange={() => onToggle({ ...resume, capabilities: resume.capabilities.map(c => c.key === capability.key ? { ...c, selected: !c.selected } : c) })} />
                <div><strong>{capability.name}</strong><p>{capability.description}</p>
                    <div className="recruit-resource-tags">{[...capability.skill_ids, ...capability.tool_ids].map(id =>
                        <span key={id}><IconTools size={11} />{resources.get(id) || '市场能力'}</span>)}
                        {!capability.skill_ids.length && !capability.tool_ids.length && <span>岗位指令</span>}
                    </div>
                    {capability.needs_setup.map(item => <p className="recruit-pending" key={item}>待准备 · {item}</p>)}
                </div>
            </label>)}</div>
        </section>
        <section className="recruit-section"><h3>交付什么</h3><p>{resume.output}</p></section>
        <section className="recruit-section"><h3><IconLock size={14} /> 工作边界</h3><ul>{resume.boundaries.map(item => <li key={item}>{item}</li>)}</ul></section>
        <details className="recruit-agreements"><summary>工作安排与授权约定</summary>
            {[['工作安排', resume.work_arrangement], ['记忆范围', resume.memory], ['通知方式', resume.notification], ['使用权限', resume.permissions]].map(([name, content]) =>
                <div className="recruit-agreement" key={name}><strong>{name}</strong><p>{content}</p></div>)}
            <p className="recruit-muted">面试与初次录用均仅本人使用、人工发起。定时、系统接入、共享记忆及组织权限，需在员工设置中完成对应配置。</p>
        </details>
        {!row?.hired_at && <div className="recruit-resume-footer">
            <p><IconCheck size={14} />勾选能力后确认简历，HR 将组装候选员工供你面试。</p>
            <button className="btn btn-primary" disabled={busy || count === 0 || ((!assembled || retryAssembly) && !canAssemble)} onClick={assembled && !retryAssembly ? onInterview : onAssemble}>
                {busy ? '正在处理…' : retryAssembly ? '重新组装候选员工' : assembled ? '去面试' : row?.candidate_id ? '按新简历重新组装' : '确认简历，安排面试'}<IconArrowRight size={15} />
            </button>
        </div>}
    </div>;
}
