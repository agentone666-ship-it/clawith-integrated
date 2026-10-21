export type EmployeeKind = 'personal' | 'team' | 'application' | 'enterprise' | 'subsidiary';
export type ConnectionKind = 'mcp' | 'sdk_cli' | 'rpa';

export interface EmployeeTestCase {
    kind: 'normal' | 'exception' | 'boundary';
    input: string;
    expected: string;
    reviewed: boolean;
}

export interface EmployeeSpecification {
    name: string;
    employee_kind: EmployeeKind;
    audience: string;
    objective: string;
    responsibilities: string[];
    boundaries: string[];
    output_format: string;
    acceptance_criteria: string[];
    connections: { kind: ConnectionKind; description: string }[];
    skill_ids: string[];
    tool_ids: string[];
    test_cases: EmployeeTestCase[];
}

export interface Blueprint {
    id: string;
    requirement: string;
    specification: EmployeeSpecification;
    revision: number;
    published_agent_id: string | null;
    published_at: string | null;
    updated_at: string;
}

export interface Readiness {
    ready: boolean;
    issues: { field: string; message: string }[];
    warnings: string[];
}

export interface Capability {
    id: string;
    name: string;
    description: string;
}

export interface CapabilityCatalog {
    skills: Capability[];
    tools: Capability[];
}

export const employeeKinds: Record<EmployeeKind, string> = {
    personal: '个人数字员工', team: '团队数字员工', application: '应用数字员工',
    enterprise: '企业数字员工', subsidiary: '分公司数字员工',
};

export const connectionKinds: Record<ConnectionKind, string> = {
    mcp: 'API / MCP', sdk_cli: 'SDK / CLI', rpa: 'RPA / 浏览器',
};

export function emptySpecification(): EmployeeSpecification {
    return {
        name: '', employee_kind: 'personal', audience: '', objective: '', responsibilities: [],
        boundaries: [], output_format: '', acceptance_criteria: [], connections: [],
        skill_ids: [], tool_ids: [], test_cases: [],
    };
}

export function invalidateReviews(spec: EmployeeSpecification): EmployeeSpecification {
    return { ...spec, test_cases: spec.test_cases.map(item => ({ ...item, reviewed: false })) };
}
