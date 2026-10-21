export type Scope = 'personal' | 'team' | 'application' | 'enterprise' | 'subsidiary';

export interface Capability {
    key: string;
    name: string;
    description: string;
    selected: boolean;
    skill_ids: string[];
    tool_ids: string[];
    needs_setup: string[];
}

export interface InterviewTask {
    title: string;
    instruction: string;
    look_for: string;
}

export interface Resume {
    name: string;
    role: string;
    goal: string;
    audience: string;
    scope: Scope;
    boundaries: string[];
    output: string;
    work_arrangement: string;
    memory: string;
    notification: string;
    permissions: string;
    capabilities: Capability[];
    interview_tasks: InterviewTask[];
}

export interface Interview {
    id: string;
    candidate_id: string;
    resume_hash: string;
    task: InterviewTask;
    run_id: string;
    session_id: string;
    decision: 'pass' | 'fail' | null;
    feedback: string;
    created_at: string;
}

export interface Dossier {
    id: string;
    revision: number;
    messages: { role: 'user' | 'assistant'; content: string }[];
    resume: Resume | null;
    candidate_id: string | null;
    candidate_hash: string | null;
    candidate_current: boolean;
    can_hire: boolean;
    interviews: Interview[];
    hired_at: string | null;
    created_at: string;
    updated_at: string;
}

export interface Resource { id: string; name: string; description: string }
export interface Catalog { skills: Resource[]; tools: Resource[]; truncated: boolean }
export interface Model { id: string; enabled: boolean; label?: string; model: string }
export interface InterviewDetail {
    status: string | null;
    summary: string;
    error: string;
    waiting_reason: string;
    can_continue: boolean;
    messages: { role: string; content: string }[];
    tools: { id: string; name: string; status: string; summary: string }[];
    truncated: boolean;
}

export const SCOPE_LABELS: Record<Scope, string> = {
    personal: '个人员工', team: '团队员工', application: '应用员工', enterprise: '企业员工', subsidiary: '分公司员工',
};
