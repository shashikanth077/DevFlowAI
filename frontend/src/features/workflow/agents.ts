import type { AgentExecution, AgentStatus, WorkflowDetail } from '../../types';

export interface AgentInfo {
  key: string;
  node: string;
  name: string;
  role: string;
  description: string;
}

/** The nine specialised agents, in workflow order. */
export const AGENTS: AgentInfo[] = [
  { key: 'requirement_analyst', node: 'requirement_analysis', name: 'Requirement Analyst', role: 'Business analyst', description: 'Objectives, functional & non-functional requirements, ambiguities, acceptance criteria.' },
  { key: 'repository_analyst', node: 'repository_analysis', name: 'Repository Analyst', role: 'Staff engineer', description: 'Clones the repo into an isolated workspace and maps languages, frameworks, tests and relevant files.' },
  { key: 'architect', node: 'architecture_design', name: 'Software Architect', role: 'Architect', description: 'Designs the approach, API endpoints, data models and file plan.' },
  { key: 'task_orchestrator', node: 'task_planning', name: 'Task Orchestrator', role: 'Engineering lead', description: 'Plans tasks & dependencies, routes work, runs retries and integrates results.' },
  { key: 'frontend_developer', node: 'frontend_development', name: 'Frontend Developer', role: 'Frontend engineer', description: 'Implements React/TypeScript components, API integration and UI tests.' },
  { key: 'backend_developer', node: 'backend_development', name: 'Backend Developer', role: 'Backend engineer', description: 'Implements endpoints, services, schemas, models and backend tests.' },
  { key: 'qa_engineer', node: 'testing', name: 'QA & Testing', role: 'QA engineer', description: 'Runs tests, lint and build inside the Docker sandbox and analyses failures.' },
  { key: 'code_reviewer', node: 'code_review', name: 'Code Review & Security', role: 'Independent reviewer', description: 'Reviews the diff for bugs, vulnerabilities, secrets and unnecessary changes.' },
  { key: 'release_engineer', node: 'github_release', name: 'GitHub Release', role: 'Release engineer', description: 'Creates the feature branch, commits approved files, pushes and opens the PR.' },
];

const STAGE_LABELS: Record<string, string> = {
  requirement_analysis: 'Requirement analysis',
  repository_analysis: 'Repository analysis',
  architecture_design: 'Architecture design',
  task_planning: 'Task planning',
  frontend_development: 'Frontend development',
  backend_development: 'Backend development',
  development_join: 'Integrating changes',
  execution_approval: 'Awaiting execution approval',
  testing: 'Testing',
  code_review: 'Code review',
  release_approval: 'Awaiting release approval',
  github_release: 'GitHub release',
  max_retries_exceeded: 'Retry limit reached',
  completed: 'Completed',
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, ' ');
}

export interface AgentProgress extends AgentInfo {
  status: AgentStatus;
  executions: AgentExecution[];
  retries: number;
  relevant: boolean;
}

/** Derive each agent's current status from its execution records. */
export function agentProgress(workflow: WorkflowDetail): AgentProgress[] {
  const roles = new Set(workflow.tasks.map((t) => t.assigned_agent));
  const planned = workflow.tasks.length > 0;
  return AGENTS.map((agent) => {
    const executions = workflow.agent_executions.filter((e) => e.node === agent.node);
    const latest = executions[executions.length - 1];
    const relevant =
      agent.key === 'frontend_developer' ? !planned || roles.has('frontend') : agent.key === 'backend_developer' ? !planned || roles.has('backend') : true;
    let status: AgentStatus = latest ? latest.status : 'pending';
    if (!latest && (!relevant || workflow.status === 'cancelled' || workflow.status === 'failed')) status = 'cancelled';
    return { ...agent, status, executions, retries: Math.max(0, executions.length - 1), relevant };
  });
}

export function overallProgress(workflow: WorkflowDetail): number {
  if (workflow.status === 'completed') return 100;
  const agents = agentProgress(workflow).filter((a) => a.relevant);
  const done = agents.filter((a) => a.status === 'completed').length;
  return Math.round((done / agents.length) * 100);
}
