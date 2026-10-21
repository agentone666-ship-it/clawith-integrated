import { fetchJson } from '../../services/api';
import type { Blueprint, CapabilityCatalog, EmployeeKind, EmployeeSpecification, Readiness } from './contracts';

export const studioApi = {
    list: (offset: number) => fetchJson<Blueprint[]>(`/employee-studio/blueprints?offset=${offset}&limit=30`),
    catalog: () => fetchJson<CapabilityCatalog>('/employee-studio/catalog'),
    generate: (requirement: string, employee_kind: EmployeeKind, model_id: string) =>
        fetchJson<EmployeeSpecification>('/employee-studio/generate', {
            method: 'POST', body: JSON.stringify({ requirement, employee_kind, model_id }),
        }),
    save: (blueprint: Blueprint | null, requirement: string, specification: EmployeeSpecification) =>
        fetchJson<Blueprint>(`/employee-studio/blueprints${blueprint ? `/${blueprint.id}` : ''}`, {
            method: blueprint ? 'PUT' : 'POST',
            body: JSON.stringify({ requirement, specification, expected_revision: blueprint?.revision ?? 0 }),
        }),
    check: (id: string) => fetchJson<Readiness>(`/employee-studio/blueprints/${id}/check`, { method: 'POST' }),
    create: (blueprint: Blueprint, modelId: string) => fetchJson<{ id: string }>('/agents/', {
        method: 'POST', body: JSON.stringify({
            name: blueprint.specification.name,
            employee_blueprint_id: blueprint.id,
            employee_blueprint_revision: blueprint.revision,
            primary_model_id: modelId,
        }),
    }),
};
