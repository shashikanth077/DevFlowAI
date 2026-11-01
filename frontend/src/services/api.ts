import axios, { AxiosError } from 'axios';
import type {
  AppSettings,
  DashboardStats,
  GitHubBranch,
  GitHubRepo,
  GitHubStatus,
  IntegrationsStatus,
  LLMTestResult,
  McpServerTest,
  Project,
  PullRequest,
  Repository,
  SettingsUpdate,
  TraceInfo,
  User,
  WorkflowDetail,
  WorkflowLog,
  WorkflowResults,
  WorkflowSummary,
} from '../types';

const TOKEN_KEY = 'devflow.token';

export const tokenStorage = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string | null): void {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage unavailable (private mode) - token lives in memory only */
    }
  },
};

export const http = axios.create({ baseURL: import.meta.env.VITE_API_URL ?? '', timeout: 60_000 });

http.interceptors.request.use((config) => {
  const token = tokenStorage.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) onUnauthorized?.();
    return Promise.reject(error);
  },
);

/** Turn any API error into a human readable message for the dashboard. */
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d: { loc?: string[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`)
        .join('; ');
    }
    if (error.code === 'ECONNABORTED') return 'The request timed out.';
    if (!error.response) return 'Cannot reach the DevFlow AI API. Is the backend running?';
    return `Request failed with status ${error.response.status}`;
  }
  return error instanceof Error ? error.message : String(error);
}

const data = <T,>(promise: Promise<{ data: T }>): Promise<T> => promise.then((r) => r.data);

export const api = {
  register: (body: { email: string; password: string; full_name?: string }) =>
    data<User>(http.post('/api/auth/register', body)),
  login: (body: { email: string; password: string }) =>
    data<{ access_token: string }>(http.post('/api/auth/login', body)),
  me: () => data<User>(http.get('/api/auth/me')),

  dashboard: () => data<DashboardStats>(http.get('/api/dashboard/stats')),

  projects: () => data<Project[]>(http.get('/api/projects')),
  createProject: (body: { name: string; description?: string; repository_id: string; base_branch: string }) =>
    data<Project>(http.post('/api/projects', body)),

  repositories: () => data<Repository[]>(http.get('/api/repositories')),
  connectRepository: (full_name: string) => data<Repository>(http.post('/api/repositories/connect', { full_name })),

  githubStatus: () => data<GitHubStatus>(http.get('/api/github/status')),
  connectGitHub: (token: string) => data<GitHubStatus>(http.post('/api/github/connect', { token })),
  disconnectGitHub: () => http.delete('/api/github/connect'),
  githubRepos: () => data<GitHubRepo[]>(http.get('/api/github/repos')),
  githubBranches: (fullName: string) => data<GitHubBranch[]>(http.get(`/api/github/repos/${fullName}/branches`)),
  pullRequests: () => data<PullRequest[]>(http.get('/api/github/pull-requests')),
  refreshPullRequest: (id: string) => data<{ state: string; merged: boolean }>(http.get(`/api/github/pull-requests/${id}/status`)),

  workflows: (params?: { project_id?: string; status?: string }) =>
    data<WorkflowSummary[]>(http.get('/api/workflows', { params })),
  startWorkflow: (body: { project_id: string; requirement: string; base_branch?: string }) =>
    data<WorkflowDetail>(http.post('/api/workflows/start', body)),
  workflow: (id: string) => data<WorkflowDetail>(http.get(`/api/workflows/${id}`)),
  cancelWorkflow: (id: string) => data<WorkflowDetail>(http.post(`/api/workflows/${id}/cancel`)),
  approveWorkflow: (id: string, approved: boolean, comment = '') =>
    data<WorkflowDetail>(http.post(`/api/workflows/${id}/approve`, { approved, comment })),
  workflowLogs: (id: string, afterId = 0) =>
    data<WorkflowLog[]>(http.get(`/api/workflows/${id}/logs`, { params: { after_id: afterId } })),
  workflowResults: (id: string) => data<WorkflowResults>(http.get(`/api/workflows/${id}/results`)),
  workflowEventsUrl: (id: string) =>
    `${import.meta.env.VITE_API_URL ?? ''}/api/workflows/${id}/events?token=${encodeURIComponent(tokenStorage.get() ?? '')}`,

  settings: () => data<AppSettings>(http.get('/api/settings')),
  updateSettings: (body: SettingsUpdate) => data<AppSettings>(http.put('/api/settings', body)),
  testLLM: () => data<LLMTestResult>(http.post('/api/settings/test-llm')),

  integrations: () => data<IntegrationsStatus>(http.get('/api/integrations/status')),
  testMcp: () => data<{ servers: McpServerTest[] }>(http.post('/api/integrations/mcp/test', undefined, { timeout: 180_000 })),
  testLangSmith: () => data<{ ok: boolean; message: string }>(http.post('/api/integrations/langsmith/test')),
  workflowTrace: (id: string, resolveUrls = false) =>
    data<TraceInfo>(http.get(`/api/workflows/${id}/trace`, { params: { resolve_urls: resolveUrls } })),
};
