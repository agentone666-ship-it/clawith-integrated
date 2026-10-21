import { request } from './api';
import type { Catalog, Dossier, InterviewDetail, InterviewTask, Resume } from '../pages/recruitment/types';

const base = '/recruitment';
const post = <T>(path: string, data: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(data) });

export const recruitmentApi = {
    list: () => request<Dossier[]>(base),
    create: () => post<Dossier>(base, {}),
    get: (id: string) => request<Dossier>(`${base}/${id}`),
    catalog: () => request<Catalog>(`${base}/catalog`),
    talk: (row: Dossier, content: string, modelId?: string) => post<Dossier>(`${base}/${row.id}/talk`, {
        revision: row.revision, content, model_id: modelId || null,
    }),
    saveResume: (row: Dossier, resume: Resume) => request<Dossier>(`${base}/${row.id}/resume`, {
        method: 'PUT', body: JSON.stringify({ revision: row.revision, resume }),
    }),
    start: (row: Dossier, task: InterviewTask, requestId: string) => post<Dossier>(`${base}/${row.id}/interviews`, {
        revision: row.revision, task, request_id: requestId,
    }),
    detail: (id: string, interviewId: string) => request<InterviewDetail>(`${base}/${id}/interviews/${interviewId}`),
    review: (row: Dossier, interviewId: string, decision: 'pass' | 'fail', feedback: string) =>
        post<Dossier>(`${base}/${row.id}/interviews/${interviewId}/review`, { revision: row.revision, decision, feedback }),
    continue: (row: Dossier, interviewId: string, content: string) =>
        post<Dossier>(`${base}/${row.id}/interviews/${interviewId}/continue`, {
            revision: row.revision, content, request_id: crypto.randomUUID(),
        }),
    cancel: (row: Dossier, interviewId: string) => post<Dossier>(`${base}/${row.id}/interviews/${interviewId}/cancel`, {
        revision: row.revision,
    }),
    hire: (row: Dossier) => post<Dossier>(`${base}/${row.id}/hire`, { revision: row.revision }),
};
