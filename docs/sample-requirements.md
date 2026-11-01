# Sample requirements and an example workflow

Paste any of these into **Create Project → Software requirement**. They are written the way a product
owner would write them. The Requirement Analyst turns each one into acceptance criteria and open questions.

## Backend-only

**Health endpoint**
> Add a `GET /api/health` endpoint that returns `{"status": "ok", "version": <app version>}` with HTTP 200,
> plus an automated test for it.

**Input validation**
> Validate the user registration payload: email must be a valid address, and password must be at least
> 12 characters with one digit. Return clear 422 error messages and cover the rules with unit tests.

**Pagination**
> The `GET /api/items` endpoint returns every row. Add `limit` (default 20, max 100) and `offset` query
> parameters, return `{"items": [...], "total": n}`, reject invalid values with 422, and add tests.

## Frontend-only

**Empty state**
> When the todo list is empty, show an illustration-free empty state with the text "Nothing to do yet" and
> a button that focuses the "new todo" input. Add a component test.

**Loading and error states**
> The products page shows a blank screen while loading and when the API fails. Add a loading spinner and
> an error message with a "Retry" button. Cover both states with tests.

## Full-stack (frontend and backend agents work together)

**Todo filtering**
> Allow users to filter the todo list by status (all, active, completed). Add a filter control above the
> list in the UI, support a `?status=` query parameter on the list API, validate unknown values with HTTP
> 422, and add tests for both frontend and backend.

**Favourites**
> Users want to mark articles as favourites. Add a `POST/DELETE /api/articles/{id}/favorite` endpoint and a
> heart toggle button on each article card that shows the current state, handles errors, and updates
> without a page reload.

---

## Example workflow (what happens, step by step)

Requirement: *"Add a subtract function to the calculator module."* The target is a Python repository
with `app/calc.py` and `tests/test_calc.py`. This is exactly the scenario exercised by
`backend/tests/test_workflow_e2e.py`.

| Step | Agent / gate | What you see in the dashboard |
|------|--------------|-------------------------------|
| 1 | Requirement Analyst | Title *"Add subtract function"*, FR-1 `subtract(a, b)` returns `a - b`, the acceptance criterion `subtract(5, 3) == 2`, and an open question: *"Should floats be supported?"* |
| 2 | Repository Analyst | Clone of `main`, a Python component with `python -m pytest -q` detected, relevant files `app/calc.py` and `tests/test_calc.py` |
| 3 | Architect | Approach *"add a pure function next to add()"*, a file plan of 2 modifications |
| 4 | Task Orchestrator | Task `T1 [backend] Implement subtract`. The frontend agent is skipped because there is no frontend work |
| 5 | Backend Developer | Edits both files; the diff appears in **Code changes** |
| 6 | 👤 Execution approval | Shows `pip install -r requirements.txt` and `python -m pytest -q` in `python:3.11-slim`, with network disabled |
| 7 | QA (attempt 1) | pytest fails, for example because `subtract` returned `a + b`. The failure analysis routes it to **backend** |
| 8 | Backend Developer (retry 1) | Receives the failing output and fixes the sign |
| 9 | QA (attempt 2) | All commands exit with 0, so the status is **passed** |
| 10 | Code Review & Security | Automated checks are clean and the LLM review approves; the diff fingerprint is recorded |
| 11 | 👤 Release approval | Shows branch `devflow/add-subtract-function-<id>`, the 2 files, tests passed and the review approved |
| 12 | GitHub Release | Commits only the approved files, pushes the branch and opens the PR; **GitHub results** shows the branch, commit and PR link |
