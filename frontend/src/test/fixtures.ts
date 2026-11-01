import type { WorkflowDetail } from '../types';

export function workflowFixture(overrides: Partial<WorkflowDetail> = {}): WorkflowDetail {
  return {
    id: 'wf-1',
    project_id: 'p-1',
    project_name: 'Calc',
    repository_full_name: 'acme/calc',
    requirement: 'Add a subtract function',
    base_branch: 'main',
    feature_branch: 'devflow/add-subtract-wf1',
    status: 'running',
    current_stage: 'testing',
    retry_count: 1,
    pull_request_url: null,
    created_at: '2026-01-01T10:00:00Z',
    completed_at: null,
    max_retries: 3,
    cancel_requested: false,
    pending_approval: null,
    approvals: [],
    requirement_analysis: null,
    repository_analysis: null,
    architecture_plan: null,
    error_details: null,
    commit_id: null,
    started_at: '2026-01-01T10:00:00Z',
    tasks: [
      { id: 't1', task_key: 'T1', position: 0, title: 'Implement subtract', description: '', assigned_agent: 'backend', status: 'completed', dependencies: [], target_files: ['app/calc.py'], acceptance_criteria: [], attempts: 2, notes: '' },
    ],
    agent_executions: [
      { id: 'a1', agent_name: 'requirement_analyst', node: 'requirement_analysis', attempt: 1, status: 'completed', started_at: '2026-01-01T10:00:00Z', finished_at: '2026-01-01T10:00:05Z', duration_ms: 5000, output: { acceptance_criteria: '1 items' }, error: null },
      { id: 'a2', agent_name: 'backend_developer', node: 'backend_development', attempt: 1, status: 'completed', started_at: '2026-01-01T10:01:00Z', finished_at: null, duration_ms: 1000, output: null, error: null },
      { id: 'a3', agent_name: 'qa_engineer', node: 'testing', attempt: 1, status: 'completed', started_at: '2026-01-01T10:02:00Z', finished_at: null, duration_ms: 1000, output: null, error: null },
      { id: 'a4', agent_name: 'backend_developer', node: 'backend_development', attempt: 2, status: 'completed', started_at: '2026-01-01T10:03:00Z', finished_at: null, duration_ms: 1000, output: null, error: null },
      { id: 'a5', agent_name: 'qa_engineer', node: 'testing', attempt: 2, status: 'running', started_at: '2026-01-01T10:04:00Z', finished_at: null, duration_ms: null, output: null, error: null },
    ],
    ...overrides,
  };
}
