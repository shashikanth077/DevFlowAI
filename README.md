# DevFlow AI

**Autonomous multi-agent software engineering platform.** Describe a requirement in plain language,
pick a GitHub repository and base branch, and a team of nine specialised AI agents, orchestrated by
a LangGraph `StateGraph`, analyses the requirement, studies the codebase, designs the change, writes
the code, runs the tests in an isolated Docker sandbox, reviews the diff, and opens a pull request.
A human approves each step that has side effects.

> 📘 **Interactive guide:** open [`docs/devflow-ai-guide.html`](docs/devflow-ai-guide.html) in a browser. It walks through the
> architecture, the LangGraph workflow (with a step-through simulator), each agent, the security model and the API.

```
 Requirement ─► Requirement Analyst ─► Repository Analyst ─► Architect ─► Task Orchestrator
                                                                              │
                          ┌───────────────────────────────────────────────────┤ (parallel or ordered by dependencies)
                          ▼                                                   ▼
                 Frontend Developer                                   Backend Developer
                          └──────────────► integrate diff ◄───────────────────┘
                                                │
                                  👤 approve sandboxed execution
                                                │
                       ┌──────────── QA & Testing (Docker sandbox) ◄───────────────┐
                tests fail│ (retry ≤ N, feedback → responsible developer)          │
                          └───────────────────────────────────────────────────────►│
                                                │ tests pass
                                   Code Review & Security ── rejected ──► developer(s) ─┘
                                                │ approved
                                  👤 approve push + pull request
                                                │
                                      GitHub Release Agent ─► feature branch, commit, PR URL
```

---

## Contents

1. [What is implemented](#what-is-implemented)
2. [Architecture](#architecture)
3. [Agents and the LangGraph workflow](#agents-and-the-langgraph-workflow)
4. [LangSmith observability and MCP tools](#langsmith-observability-and-mcp-tools)
5. [Project structure](#project-structure)
6. [Quick start (Docker Compose)](#quick-start-docker-compose)
7. [Local development](#local-development)
8. [Configuration](#configuration)
9. [Using DevFlow AI](#using-devflow-ai)
10. [Security model](#security-model)
11. [REST API](#rest-api)
12. [Testing](#testing)
13. [Limitations and planned work](#limitations-and-planned-work)

---

## What is implemented

All six development phases from the specification are implemented and covered by tests.

| Phase | Scope | Status |
|------:|-------|--------|
| 1 | FastAPI backend, React dashboard, Ollama integration, Requirement Analyst with structured (Pydantic) output | ✅ Implemented |
| 2 | GitHub integration (token connect, repos, branches), isolated clone and inspection, Architecture Agent, Task Orchestrator | ✅ Implemented |
| 3 | Frontend and Backend Development Agents writing real files (with overwrite guards), Docker sandbox | ✅ Implemented |
| 4 | QA Agent (tests, lint, build in sandbox), correction loops with retry limit, Code Review & Security Agent | ✅ Implemented |
| 5 | Feature branch, commit of approved files only, push, pull request via GitHub API, human approval gates | ✅ Implemented |
| 6 | Real-time updates (SSE), workflow history, checkpoint recovery, structured logging, documentation | ✅ Implemented |

**How it was verified**

- **Backend: 96 pytest tests.** These cover the security helpers, the LLM service (Ollama and OpenAI-compatible
  wire formats, validation retries, redaction), repository inspection and path-safety guards, every agent,
  routing and reducers, the REST API, Docker sandbox isolation, and complete **end-to-end LangGraph runs
  through the REST API**. The end-to-end runs include a test failure followed by a correction loop, a review
  rejection, the max-retry limit, cancellation, rejected approvals, **crash recovery from a checkpoint**, and
  a run where **pytest really executes inside the Docker sandbox**. The suite passes on SQLite and on PostgreSQL.
- **Frontend: 23 Vitest + React Testing Library tests**, a clean `tsc` type-check and a production build.
- In tests the LLM is a scripted test double, and so is the GitHub REST API (an httpx mock transport). Git
  clone, commit and push run for real against a local bare repository.

## Architecture

| Layer | Technology | Notes |
|-------|------------|-------|
| Dashboard | React 19, TypeScript, Vite, Material UI, Redux Toolkit, Axios | SSE live updates with a polling fallback |
| API | FastAPI, Pydantic v2 | JWT auth, typed request/response models, correct status codes |
| Orchestration | LangGraph `StateGraph` | Conditional edges, parallel fan-out, `interrupt()` approval gates, checkpointing |
| LLM | `LLMService` with Ollama / OpenAI / Mistral providers | JSON-schema constrained output, validation + self-correction, per-agent models |
| Persistence | PostgreSQL + SQLAlchemy 2 + Alembic | Every run, agent execution, task, diff, test, review and PR is stored |
| Checkpoints | `PostgresSaver` (or SQLite / memory) | Thread id = workflow id; resumes after restart |
| Sandbox | Docker CLI | `docker cp` (no mounts), `--network none`, CPU/mem/PID limits, `--cap-drop ALL`, timeouts |
| Git/GitHub | git CLI + GitHub REST API | Token passed through environment variables only, never in argv, `.git/config` or prompts |

The process model is a single API process. Workflows run on a thread pool inside it and post events to the
`workflow_logs` table. The SSE endpoint streams those events, so live updates also work behind a proxy.

## Agents and the LangGraph workflow

| # | Agent | Node(s) | Output |
|---|-------|---------|--------|
| 1 | Requirement Analyst | `requirement_analysis` | `RequirementAnalysis` with objectives, FR/NFRs, ambiguities, assumptions, acceptance criteria, proposed tasks |
| 2 | Repository Analyst | `repository_analysis` | Clone and deterministic scan (languages, frameworks, components, test/install/lint/build commands), plus LLM insights (architecture, conventions, relevant files, validated against disk) |
| 3 | Software Architect | `architecture_design` | `ArchitecturePlan` with approach, FE/BE changes, API endpoints, data models, file plan, testing strategy, risks |
| 4 | Task Orchestrator | `task_planning`, `development_join`, `max_retries_exceeded` + routing | Validated task DAG (unique ids, known deps, cycles broken, agent matched to repo), execution order, retry routing |
| 5 | Frontend Developer | `frontend_development` | Complete-file edits for UI tasks; runs only if frontend work exists |
| 6 | Backend Developer | `backend_development` | Complete-file edits for API/data tasks; runs only if backend work exists |
| 7 | QA & Testing | `testing` | `TestReport` with per-command exit codes and output, failure analysis routed to the responsible developer, coverage notes |
| 8 | Code Review & Security | `code_review` | `ReviewReport` combining an LLM review with automated checks (secrets, scope, deletions, debug code, test status), plus a diff fingerprint |
| 9 | GitHub Release | `github_release` | Feature branch, commit of the approved files, push, PR; returns branch, commit SHA and PR URL |

**Shared state.** `ProjectState` (`backend/app/orchestration/state.py`) contains every field from the
specification (`project_id`, `repository_url`, `repository_path`, `base_branch`, `feature_branch`,
`user_requirement`, `acceptance_criteria`, `repository_analysis`, `architecture_plan`,
`development_tasks`, `generated_files`, `modified_files`, `test_results`, `review_feedback`,
`workflow_status`, `retry_count`, `commit_id`, `pull_request_url`, `error_details`). It also holds
control fields: `fix_feedback`, `active_agents`, `file_ownership`, approvals, and the approved diff hash.
The two developers can run in the same super-step, so the keys they write use reducers. Terminal
statuses are sticky.

**Conditional edges** (`backend/app/orchestration/routing.py`):

| Condition | Route |
|-----------|-------|
| Tests passed (or explicitly *not run*) | `testing → code_review` |
| Tests failed, retries left | `testing → frontend/backend_development` (only the responsible agents, with failure output) |
| Review approved | `code_review → release_approval` |
| Review rejected, retries left | `code_review → responsible developer(s)` with the blocking findings |
| Maximum retry reached | `→ max_retries_exceeded → END` (workflow `failed`) |
| Cancellation / unrecoverable error | any node `→ END` |
| Frontend task depends on backend task | developers run sequentially (backend then frontend), otherwise in parallel |

**Human approval gates** use LangGraph `interrupt()`:

1. `execution_approval`: shown before any generated code runs. It lists the exact sandbox image and the
   setup, test, lint and build commands, plus the network policy. Approval is asked for once per workflow.
2. `release_approval`: shown before any push or pull request. It shows the branch, the files, the test
   status and the review verdict.

Approving calls `POST /api/workflows/{id}/approve`, which resumes the graph with
`Command(resume=...)`. Rejecting cancels the workflow, and nothing is pushed.

**Checkpointing and recovery.** A checkpoint is written after every super-step. If the API process dies
mid-run, it resumes `queued`/`running` workflows from their last checkpoint on the next start, and
completed stages are not re-run. `test_checkpoint_recovery_after_crash` covers this.

**Failure handling.** Each node runs inside a wrapper that checks for cancellation, records an
`AgentExecution`, enforces `AGENT_TIMEOUT_SECONDS`, and converts any exception into
`workflow_status=failed` with `error_details`, which the dashboard shows. Failures are never silently ignored.

## LangSmith observability and MCP tools

### LangSmith tracing

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` (standard names; `LANGCHAIN_*` aliases also work) and every
workflow becomes a trace in the `LANGSMITH_PROJECT` project (default `devflow-ai`):

```
devflow-workflow                       root run (one per execution segment; all share thread_id = workflow id)
 ├─ requirement_analysis               LangGraph node
 │   └─ llm:requirement_analyst        LLM call: model, temperature, input/output tokens, latency, retries
 ├─ architecture_design
 │   ├─ mcp:devflow-repo.read_file     MCP tool call (run_type=tool)
 │   └─ llm:architect
 ├─ backend_development / frontend_development / testing / code_review / github_release ...
```

- **Segments:** a workflow pauses at each approval gate, so a run produces one root run per segment
  (`devflow-workflow`, then `devflow-workflow-resume`). The ids are stored on the workflow, shown on the
  **Tools & traces** tab and returned by `GET /api/workflows/{id}/trace`.
- **Feedback:** human approvals (`human_approval_execution` / `human_approval_release`), `tests_passed`,
  `review_approved`, `workflow_completed` and `retries_used` are attached to the trace, so LangSmith can
  filter and chart workflow quality.
- **Privacy:** prompts contain your source code, so every trace goes through one explicit client with a
  redaction hook: credentials are scrubbed and very long fields truncated. `LANGSMITH_HIDE_CONTENT=true` sends
  only the structure (counts, ids, metadata) and no prompts, code or outputs. The library's global env tracing
  is switched off at startup, so a stray `LANGSMITH_TRACING` can never create an unredacted duplicate.
- **Never fatal:** tracing failures are logged and never fail a workflow. The dashboard's Settings page has a
  **Test LangSmith connection** button.

### MCP (Model Context Protocol) tools

MCP is used in **both directions**.

**1. Agents use MCP tools (DevFlow is an MCP client).** When enabled, the architect, developers, reviewer and
requirement analyst run a short tool loop before they answer: the model picks a tool (or finishes), the broker
runs it, and the result is added to the prompt. This uses the same schema-validated JSON path as every other
agent output, so it works identically with Ollama, OpenAI and Mistral and needs no provider-specific tool-calling.

- **Built-in `devflow-repo` server** (`app/mcp_tools/repo_server.py`): `list_directory`, `read_file`,
  `search_code`, `git_log`, `git_status`, `git_diff`. It lets agents explore a repository on demand instead of
  having whole files stuffed into prompts. It reuses the workspace guards (no traversal, no `.git`, no credential
  files) and never modifies the repository or its index.
- **Your own servers:** list them in a JSON file and set `MCP_SERVERS_FILE` ([example](docs/mcp_servers.example.json);
  both the `{"servers": [...]}` and the Claude-style `{"mcpServers": {...}}` layouts are accepted). Transports:
  stdio and streamable HTTP. Use it for documentation lookup, an issue tracker, a security-advisory feed, etc.
- **Policy** (`app/mcp_tools/broker.py`): a tool is callable only if it advertises `readOnlyHint` (or the
  operator allow-lists it); destructive and unannotated tools are blocked and the attempt is audited. Servers are
  scoped to the agents named in their config. There is a per-agent call limit (`MCP_MAX_TOOL_CALLS`), a
  per-workflow budget, argument validation against the tool's JSON schema, timeouts, and secret redaction and
  truncation of results.
- **Prompt injection:** tool output is treated as untrusted data. It is wrapped in delimiters and labelled, the
  model is instructed never to follow instructions inside it, and it cannot change tools or policy. A tool result
  cannot trigger writes anywhere, because only read-only tools are reachable at all.
- **Trust boundary:** a stdio entry is a command that runs on the backend host, so servers come only from the
  operator's file, never from the API or browser. Users opt in (Settings → *Let agents call MCP tools*) and
  can switch individual servers off. Server child processes receive a minimal environment, not DevFlow's secrets.
- **Audit:** every call (allowed, blocked or failed) is stored in `tool_calls`, shown on the workflow's
  **Tools & traces** tab and traced in LangSmith.

**2. DevFlow is an MCP server** (`python -m app.mcp_tools.devflow_server`). It lets MCP clients such as Claude Code
or Claude Desktop drive DevFlow: `list_projects`, `start_workflow`, `list_workflows`, `get_workflow`,
`get_workflow_logs`, `get_workflow_results`, `cancel_workflow`. There is **deliberately no approve tool**: the
sandbox-execution and push/PR gates stay human-only, so an AI client cannot approve its own work. Configuration
example: [`docs/claude-code-mcp.example.json`](docs/claude-code-mcp.example.json). It authenticates with a DevFlow
access token (`DEVFLOW_API_TOKEN`) and sees only that user's data.

## Project structure

```
backend/
  app/
    main.py                     FastAPI app, /health, error handlers, startup recovery
    api/deps.py                 auth + ownership dependencies
    api/routes/                 auth, projects, repositories, github, workflows (+SSE), settings, dashboard
    agents/                     the 9 agents (+ base.py, development.py shared by FE/BE developers)
    orchestration/              state.py, graph.py, nodes.py, routing.py, checkpointing.py, runtime.py
    observability/              tracing.py - LangSmith client, redaction, feedback
    mcp_tools/                  MCP client (config, connection, broker, loop) + repo_server + devflow_server
    services/                   llm_service, github_service, repository_service, execution_service,
                                workflow_service (runner/persistence/approvals), settings_service
    schemas/                    Pydantic models for API and for every agent's structured output
    models/                     SQLAlchemy models (users, settings, GitHub, projects, workflows, tasks, ...)
    database/                   engine + session management
    core/                       config, security (JWT, PBKDF2, Fernet, secret scanning), logging, errors
  alembic/                      migrations (0001_initial_schema)
  tests/                        96 tests (unit, API, end-to-end graph, MCP, tracing, Docker sandbox)
  Dockerfile  requirements.txt  requirements-dev.txt
frontend/
  src/
    pages/                      Dashboard, CreateProject, Workflows (history), WorkflowDetail, Settings, Login
    features/workflow/          AgentMonitor, ApprovalPanel, TaskBoard, CodeChanges, TestResults, GitHubResults, LogViewer
    components/                 Layout, DiffViewer, StatusChip, StatCard, ...
    hooks/                      useAsync, useWorkflowStream (SSE)
    services/api.ts             Axios client
    store/                      Redux Toolkit (auth, notifications)
    types/                      API types
  Dockerfile  nginx.conf
docs/devflow-ai-guide.html      interactive learning & documentation guide
docs/sample-requirements.md     sample requirements and an example workflow
docker-compose.yml  .env.example
```

## Quick start (Docker Compose)

Prerequisites: Docker with Compose v2. A GPU is optional; Ollama runs on CPU but more slowly.

```bash
cp .env.example .env
```

Set `SECRET_KEY` in `.env`, and set `DOCKER_GID` to the group id of your Docker socket:

```bash
stat -c %g /var/run/docker.sock
```

Start everything. This also pulls the `LLM_MODEL` into Ollama on first start, which takes a while:

```bash
docker compose up -d --build
```

Watch the model download:

```bash
docker compose logs -f ollama-pull
```

Then open the dashboard at http://localhost:3000. The API docs are at http://localhost:8000/docs, and the
health check is at http://localhost:8000/health.

## Local development

**1. Ollama**

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

```bash
ollama serve
```

In another terminal:

```bash
ollama pull llama3.1:8b
```

Coding-oriented models such as `qwen2.5-coder:14b` produce noticeably better code. Pin them per agent in **Settings**.

**2. PostgreSQL**

```bash
docker compose up -d postgres
```

**3. Backend** (Python 3.11+)

```bash
cd backend
```

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
export DATABASE_URL=postgresql+psycopg://devflow:devflow@localhost:5432/devflow
```

```bash
alembic upgrade head
```

```bash
uvicorn app.main:app --reload --port 8000
```

**4. Frontend** (Node 20+)

```bash
cd frontend
```

```bash
npm install
```

```bash
npm run dev
```

Open http://localhost:5173. Vite proxies `/api` to `localhost:8000`.

**5. Sandbox images.** Pre-pull these so the first QA run is fast:

```bash
docker pull python:3.11-slim && docker pull node:20-slim
```

## Configuration

All settings are environment variables; see [`.env.example`](.env.example) for the full list. The most important:

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | *(must set)* | JWT signing and key derivation for encrypted secrets |
| `DATABASE_URL` | `postgresql+psycopg://devflow:devflow@localhost:5432/devflow` | Database (SQLite also supported) |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_TEMPERATURE` | `ollama` / `llama3.1:8b` / `0.2` | Defaults for new users (editable in Settings) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama endpoint |
| `OPENAI_API_KEY`, `MISTRAL_API_KEY` | – | Optional server-wide keys (users can store their own, encrypted) |
| `GITHUB_TOKEN` | – | Optional server-wide token (users normally connect their own in Settings) |
| `PROTECTED_BRANCH_PATTERNS` | `main,master,develop,production,release/*` | The release agent never pushes to these |
| `SANDBOX_ALLOW_NETWORK_FOR_INSTALL` | `false` | Network during dependency install (tests always run offline) |
| `SANDBOX_CPUS` / `SANDBOX_MEMORY` / `SANDBOX_COMMAND_TIMEOUT_SECONDS` | `1.0` / `1g` / `600` | Sandbox limits |
| `WORKFLOW_MAX_RETRIES` | `3` | Correction rounds before the workflow fails |
| `REQUIRE_EXECUTION_APPROVAL` / `REQUIRE_RELEASE_APPROVAL` | `true` | Human approval gates |
| `AGENT_TIMEOUT_SECONDS` | `900` | Hard timeout per agent |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | `false` / – / `devflow-ai` | LangSmith tracing |
| `LANGSMITH_HIDE_CONTENT` | `false` | Send only metadata; never prompts, code or outputs |
| `MCP_ENABLED` / `MCP_BUILTIN_REPO_SERVER` | `true` / `true` | Server-wide MCP switch; built-in repository tools |
| `MCP_SERVERS_FILE` | – | Operator-approved extra MCP servers (JSON) |
| `MCP_MAX_TOOL_CALLS` / `MCP_TOOL_TIMEOUT_SECONDS` | `6` / `60` | Tool-use limits per agent run |

> **Network during install.** Tests always run with networking disabled. Dependency installation is also
> offline by default, which fails for most real repositories. When you trust the repository's dependency
> manifests, enable *Allow network access during dependency installation* in **Settings**.

## Using DevFlow AI

1. **Sign up / sign in** at the dashboard.
2. **Settings → GitHub connection:** paste a fine-grained personal access token with access to the target
   repositories. It needs *Contents: read & write*, *Pull requests: read & write* and *Metadata: read*.
   The token is validated against GitHub, encrypted at rest, and never returned to the browser.
3. **Settings → LLM provider:** pick Ollama, OpenAI or Mistral and a model, then click **Test connection**.
   You can pin individual agents to different models. Pinning the reviewer to a different model gives a more independent review.
4. **Create Project:** choose a repository, a base branch and a requirement. Sample requirements are one
   click away; more are in [`docs/sample-requirements.md`](docs/sample-requirements.md). Click **Start workflow**.
5. **Agent Execution Monitor:** watch each agent go Pending → Running → Completed/Failed, with outputs,
   logs, retries and the current stage. The **Analysis**, **Tasks**, **Code changes**, **Tests & review**,
   **GitHub results** and **Logs** tabs fill in as the run progresses.
6. **Approve execution:** review the exact sandbox commands, then approve.
7. **Approve release:** check the diff, test results and review verdict, then approve. You get the
   branch, commit and pull request link. Review and merge on GitHub; DevFlow AI never merges.

## Security model

- **Tokens:** GitHub and LLM API keys are Fernet-encrypted in the database. They are never returned by the
  API, never placed in LangGraph state or checkpoints, and never logged. Git authentication uses
  `GIT_CONFIG_*` environment variables (an `http.extraheader`), so the token appears in neither process
  arguments nor `.git/config`.
- **Prompt hygiene:** every prompt passes through `redact_secrets()`. Credential files (`.env*`, keys,
  `.npmrc`, ...) are never read into prompts or written by agents.
- **File-system guards:** these block path traversal, absolute paths, `.git/`, vendor/build directories,
  symlink escapes, files owned by the other developer agent, overwriting an existing file whose content
  the agent was not shown, truncated rewrites (more than 70% of lines dropped), and placeholder content
  such as "rest of code unchanged".
- **Sandbox:** generated code runs only in Docker containers. The workspace is copied in with `docker cp`,
  so there are no bind mounts. The Docker socket is never exposed, all Linux capabilities are dropped,
  `no-new-privileges` is set, CPU, memory and PID limits apply, network is `none` for tests, timeouts kill
  hung commands, and containers and images are removed afterwards. If Docker is unavailable, QA fails
  instead of running anything on the host.
  *Note:* the backend container mounts the Docker socket so that it can launch sandboxes. Treat the
  backend host as trusted infrastructure.
- **Independent review:** the reviewer is read-only and sees only the diff. It uses its own prompt and can
  use its own model. Automated blocking checks (secrets, large deletions, failing tests) override the
  LLM verdict, so the authoring agents cannot approve their own work.
- **Release integrity:** the reviewed diff is fingerprinted with SHA-256. The release agent refuses to commit
  if the workspace changed after review, stages only the approved files, refuses protected or base
  branches, and never merges.
- **Agent tools (MCP):** read-only by default, scoped per agent, size/time/call limited, redacted, audited, and treated as untrusted data; stdio server commands come only from the operator's file; the DevFlow MCP server has no approve tool.
- **Observability:** traces are redacted (and can be metadata-only); the LangSmith key is never returned by the API.
- **Auth:** PBKDF2-SHA256 password hashing, JWT bearer tokens, and per-user ownership checks on every resource.

## REST API

Interactive docs are at `/docs`. The main endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register`, `/api/auth/login` | Account and JWT |
| GET | `/api/auth/me` | Current user |
| POST / GET | `/api/projects` | Create / list projects |
| POST | `/api/repositories/connect` | Verify and register a GitHub repository |
| GET | `/api/repositories` | Connected repositories |
| POST / DELETE | `/api/github/connect` | Store / remove the GitHub token |
| GET | `/api/github/status`, `/api/github/repos`, `/api/github/repos/{owner}/{repo}/branches` | GitHub connection, repository and branch listing |
| GET | `/api/github/pull-requests`, `/api/github/pull-requests/{id}/status` | PRs created, live PR status |
| POST | `/api/workflows/start` | Start a workflow (202) |
| GET | `/api/workflows`, `/api/workflows/{id}` | History / detail (agents, tasks, approvals, analysis) |
| POST | `/api/workflows/{id}/cancel` | Cancel |
| POST | `/api/workflows/{id}/approve` | Approve/reject the pending gate `{approved, comment}` |
| GET | `/api/workflows/{id}/logs` | Logs (`after_id` for incremental reads) |
| GET | `/api/workflows/{id}/results` | File changes with diffs, test runs, reviews, PR |
| GET | `/api/workflows/{id}/events?token=` | Server-Sent Events stream |
| GET / PUT | `/api/settings`, POST `/api/settings/test-llm` | LLM/workflow settings, connectivity check |
| GET | `/api/workflows/{id}/trace` | LangSmith run ids of the workflow (`?resolve_urls=true` for links) |
| GET | `/api/integrations/status` | LangSmith and MCP status (never secrets or launch commands) |
| POST | `/api/integrations/mcp/test`, `/api/integrations/langsmith/test` | Connect to MCP servers and list tools with their policy; check LangSmith |
| GET | `/api/dashboard/stats` | Dashboard counters and recent PRs |
| GET | `/health` | Database, sandbox and Ollama health |

## Testing

Backend tests run on SQLite by default. The Docker tests run automatically when a daemon is available:

```bash
cd backend && pytest
```

To run the same suite against PostgreSQL:

```bash
TEST_POSTGRES_URL=postgresql+psycopg://devflow:devflow@localhost:5432/devflow_test pytest
```

Frontend unit tests, type-check and build:

```bash
cd frontend && npm test && npm run lint && npm run build
```

## Limitations and planned work

**Planned, not implemented:**

- MCP: OAuth for remote MCP servers (static headers/tokens from the operator's file are supported today), MCP resources/prompts (only tools are used), and sandboxing of third-party stdio servers (they run as the backend user; only add servers you trust).
- LangSmith: prompt/dataset management and automated evaluators on the collected feedback (the signals are recorded; the evaluation pipelines are not built).
- GitHub OAuth App login (personal access tokens are used today).
- Patch-based edits for very large files. Agents rewrite whole files, and files over about 15 KB are not sent to the model, so they are not edited.
- A distributed worker queue such as Celery or Arq for horizontal scaling. Today a single API process runs workflows in a thread pool.
- Per-repository custom test commands configured in the UI. Commands are auto-detected for Python, Node and Go.
- Sandbox images for other ecosystems (JVM, .NET, Ruby).
- Reviewing and editing individual diff hunks before approval.

**Known constraints:**

- Output quality depends heavily on the model. Small local models often need several correction rounds.
- With the default offline install policy, repositories whose dependencies are not preinstalled in the
  sandbox image report test failures until network access for installs is enabled.
