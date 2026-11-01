export type WorkflowStatus = 'queued' | 'running' | 'awaiting_approval' | 'completed' | 'failed' | 'cancelled';
export type AgentStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'rejected' | 'waiting';

export interface User {
  id: string;
  email: string;
  full_name: string;
}

export interface Repository {
  id: string;
  owner: string;
  name: string;
  full_name: string;
  default_branch: string;
  private: boolean;
  html_url: string;
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  base_branch: string;
  repository: Repository;
  created_at: string;
  workflow_count: number;
  last_workflow_status: WorkflowStatus | null;
}

export interface GitHubStatus {
  connected: boolean;
  login: string | null;
  scopes: string[];
  connected_at: string | null;
  source: 'user' | 'server' | null;
}

export interface GitHubRepo {
  full_name: string;
  owner: string;
  name: string;
  private: boolean;
  default_branch: string;
  html_url: string;
  description: string | null;
  updated_at: string | null;
}

export interface GitHubBranch {
  name: string;
  protected: boolean;
  sha: string;
}

export interface AgentExecution {
  id: string;
  agent_name: string;
  node: string;
  attempt: number;
  status: AgentStatus;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  output: Record<string, unknown> | null;
  error: string | null;
}

export interface Task {
  id: string;
  task_key: string;
  position: number;
  title: string;
  description: string;
  assigned_agent: 'frontend' | 'backend';
  status: string;
  dependencies: string[];
  target_files: string[];
  acceptance_criteria: string[];
  attempts: number;
  notes: string;
}

export interface CommandPlan {
  component: string;
  kind: string | null;
  image: string | null;
  setup: string[];
  test: string[];
  lint: string[];
  build: string[];
}

export interface PendingApproval {
  gate: 'execution' | 'release';
  title: string;
  description: string;
  commands?: CommandPlan[];
  changed_files?: string[];
  files?: string[];
  network_for_install?: boolean;
  repository?: string;
  base_branch?: string;
  feature_branch?: string;
  test_status?: string;
  test_summary?: string;
  review_approved?: boolean;
  review_summary?: string;
}

export interface WorkflowSummary {
  id: string;
  project_id: string;
  project_name: string;
  repository_full_name: string;
  requirement: string;
  base_branch: string;
  feature_branch: string | null;
  status: WorkflowStatus;
  current_stage: string | null;
  retry_count: number;
  pull_request_url: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface RequirementAnalysis {
  title: string;
  summary: string;
  business_objectives: string[];
  functional_requirements: { id: string; description: string; priority: string }[];
  non_functional_requirements: string[];
  ambiguities: string[];
  assumptions: string[];
  acceptance_criteria: string[];
  proposed_tasks: { title: string; description: string; area: string }[];
}

export interface WorkflowDetail extends WorkflowSummary {
  max_retries: number;
  cancel_requested: boolean;
  pending_approval: PendingApproval | null;
  approvals: { gate: string; approved: boolean; comment: string; at: string }[];
  requirement_analysis: RequirementAnalysis | null;
  repository_analysis: Record<string, any> | null;
  architecture_plan: Record<string, any> | null;
  error_details: { message?: string; node?: string; agent?: string; [key: string]: unknown } | null;
  commit_id: string | null;
  trace_run_ids: string[];
  started_at: string | null;
  agent_executions: AgentExecution[];
  tasks: Task[];
}

export interface WorkflowLog {
  id: number;
  created_at: string;
  level: 'info' | 'warning' | 'error';
  agent: string | null;
  message: string;
  data: Record<string, unknown> | null;
}

export interface FileChange {
  id: string;
  path: string;
  change_type: 'created' | 'modified' | 'deleted';
  agent: string;
  diff: string;
  additions: number;
  deletions: number;
  approved: boolean;
}

export interface CommandReport {
  component: string;
  phase: 'setup' | 'test' | 'lint' | 'build';
  command: string;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_ms: number;
  timed_out: boolean;
}

export interface TestResult {
  id: string;
  attempt: number;
  status: 'passed' | 'failed' | 'not_run' | 'error';
  summary: string;
  commands: CommandReport[];
  failures: { command: string; summary: string; responsible_agent: string; files: string[]; suggested_fix: string }[];
  coverage_notes: string[];
  duration_ms: number;
  created_at: string;
}

export interface ReviewIssue {
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  category: string;
  file: string;
  line: number | null;
  message: string;
  suggestion: string;
  responsible_agent: string;
}

export interface ReviewReport {
  id: string;
  attempt: number;
  approved: boolean;
  summary: string;
  issues: ReviewIssue[];
  automated_findings: ReviewIssue[];
  diff_hash: string;
  reviewer_model: string;
  created_at: string;
}

export interface PullRequest {
  id: string;
  workflow_id: string;
  repository_full_name: string;
  number: number;
  url: string;
  title: string;
  head_branch: string;
  base_branch: string;
  commit_sha: string;
  state: string;
  draft: boolean;
  merged: boolean;
  created_at: string;
}

export interface WorkflowResults {
  workflow_id: string;
  status: WorkflowStatus;
  feature_branch: string | null;
  commit_id: string | null;
  pull_request_url: string | null;
  file_changes: FileChange[];
  test_results: TestResult[];
  review_reports: ReviewReport[];
  tool_calls: ToolCall[];
  pull_request: PullRequest | null;
}

export interface DashboardStats {
  total_projects: number;
  active_workflows: number;
  successful_workflows: number;
  failed_workflows: number;
  awaiting_approval: number;
  recent_pull_requests: PullRequest[];
  recent_workflows: WorkflowSummary[];
}

export type LLMProvider = 'ollama' | 'openai' | 'mistral';

export interface AppSettings {
  llm_provider: LLMProvider;
  llm_model: string;
  llm_temperature: number;
  llm_base_url: string | null;
  llm_api_key_configured: boolean;
  agent_models: Record<string, string>;
  workflow_max_retries: number;
  require_execution_approval: boolean;
  require_release_approval: boolean;
  sandbox_allow_network_for_install: boolean;
  create_draft_pull_requests: boolean;
  mcp_enabled: boolean;
  mcp_disabled_servers: string[];
  available_agents: string[];
}

export type SettingsUpdate = Partial<Omit<AppSettings, 'llm_api_key_configured' | 'available_agents'>> & {
  llm_api_key?: string;
};

export interface LLMTestResult {
  ok: boolean;
  provider: string;
  model: string;
  message: string;
  available_models: string[];
}

export interface ToolCall {
  id: number;
  created_at: string;
  agent: string;
  server: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: 'ok' | 'error' | 'blocked';
  result_preview: string;
  duration_ms: number;
}

export interface TraceInfo {
  enabled: boolean;
  project: string;
  run_ids: string[];
  urls: Record<string, string | null>;
  note: string | null;
}

export interface McpServerInfo {
  name: string;
  description: string;
  transport: 'stdio' | 'http';
  builtin: boolean;
  agents: string[];
  allow_write_tools: boolean;
  enabled_for_user: boolean;
}

export interface IntegrationsStatus {
  langsmith: {
    enabled: boolean;
    api_key_configured: boolean;
    project: string;
    endpoint: string;
    hide_content: boolean;
    redaction: string;
  };
  mcp: {
    available: boolean;
    enabled_for_user: boolean;
    max_tool_calls: number;
    servers: McpServerInfo[];
    config_errors: string[];
  };
}

export interface McpToolInfo {
  name: string;
  description: string;
  read_only: boolean;
  allowed: boolean;
  reason: string;
  parameters: string[];
}

export interface McpServerTest {
  name: string;
  ok: boolean;
  error: string | null;
  tools: McpToolInfo[];
}
