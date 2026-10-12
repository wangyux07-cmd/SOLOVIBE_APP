# SoloVibe

**A context-aware companion agent for solo city outings.**

SoloVibe helps people decide what to do when they want to head out alone. It brings together how the user feels, where they are, and practical constraints such as time, budget, and walking distance to suggest a small set of actionable city activities. Once the user confirms a specific action, the agent helps them take the next step.

> **Project status: V1 redesign in progress.** Stage 0 has been delivered. Stage 1 now has a wired graph, API, and developer UI, but live model generation and database persistence have not passed integration testing. The capabilities below describe the intended V1 product; they are not all available yet.

## Why SoloVibe?

A list of nearby places does not always help someone make a decision. A useful suggestion also needs to account for their energy, available time, budget, willingness to walk, and preferences for spending time alone.

SoloVibe aims to turn those constraints into a manageable choice, with enough information to act on it.

For example:

> “I'm near Xuhui in Shanghai. I'm a little tired, have one hour and a budget of RMB 50, and don't want to walk far.”

The intended experience is to record those constraints, clarify anything essential, retrieve real place and route information, and offer at most two or three options. Each option should explain why it fits, its estimated cost and duration, its sources, and any unknowns. If the user changes their budget, subsequent planning should use the new value. Saving a plan or handing off to navigation requires confirmation of that action.

**This is an example of the target experience. The current baseline does not generate these recommendations.**

## Planned V1 Capabilities

| Capability | Intended behavior |
| --- | --- |
| Context understanding | Capture location, energy, budget, time, preferences, and exclusions; preserve user corrections across turns |
| External information retrieval | Use map services such as Amap for places and routes, with web search for supporting venue and activity information |
| Activity options | Present a small set of comparable options with timing, cost, route information, fit, and sources |
| Conversation continuity | Preserve recent messages and structured constraints; summarize older history when the input budget requires it |
| Confirmed actions | Save a plan, hand off to navigation, or provide an official booking entry point after the user confirms the action |
| Plan adjustments | Update affected parts of the plan when the user's constraints or situation change |

Ratings, offers, menus, and opening hours depend on actual provider coverage. Missing information must remain unknown, and failed calls must be reported as failures. The model must not invent a successful lookup. Automatic payments, general-purpose automated bookings, and continuous background location tracking are outside the initial scope.

## Architecture

The frontend uses **React, TypeScript, and Vite**, with **FastAPI** on the backend. **LangGraph** is the workflow orchestrator, **Supabase / PostgreSQL** is the planned persistence layer, and model calls go through a dedicated adapter.

The diagram below shows the **target V1 workflow**, not an end-to-end flow already running in the application:

```mermaid
flowchart TD
    A[User message or constraint change] --> B[FastAPI: validate request and session ownership]
    B --> C[LangGraph: assemble context]
    C --> D[Model proposes a state patch]
    D --> E[Validate and persist structured state]
    E --> F{Enough information?}
    F -->|Clarification needed| G[Ask an essential question]
    G --> A
    F -->|Ready to plan| H[Map and web search tools]
    H --> I[Validate constraints and build options]
    I --> J[Present options and sources]
    J --> K[User selects and confirms an action]
    K --> L[Save plan or hand off to an official service]
    L --> M[Record the actual outcome]
```

LangGraph coordinates node execution, conditional routing, and recovery. The model handles language understanding and explanation. Application code controls ownership, validation, request deduplication, and authorization for actions.

### Context and State

- **Raw messages:** Stored separately for conversation display and traceability.
- **Structured snapshots:** Authoritative constraints and execution progress, updated after each validated change with a version and source reference.
- **Recent messages and rolling summaries:** Recent turns retain their original text. Older history is summarized as the node's input budget fills up. The proposed initial trigger is approximately 80% of that budget; this policy is not implemented or validated yet.
- **LangGraph checkpoints:** Persist graph execution state for recovery. They do not replace business snapshots or automatically compress conversation history.

## Development Status

| Stage | Deliverable | Status |
| --- | --- | --- |
| 0 · Development baseline | Reproducible setup, locked dependencies, health checks, developer workbench, and baseline tests | Completed and pushed to the development branch |
| 1 · LangGraph and state | Graph execution, structured state, native persistence, session isolation, and retries | Graph/API/UI wired locally; live integration not yet verified |
| 2 · Context management | Token budgets, recent-message windows, rolling summaries, and recovery consistency | Planned |
| 3 · Real activity options | Map and search integrations, source evidence, constraint validation, and option presentation | Planned |
| 4 · Confirmation and actions | User confirmation, saving, navigation handoff, and local plan adjustments | Planned |
| 5 · Integration and release | End-to-end validation, failure handling, and deployment | Planned |

**Branches:** `main` retains the historical prototype. The active redesign is on [`codex/redesign-v1`](https://github.com/wangyux07-cmd/SOLOVIBE_APP/tree/codex/redesign-v1). Its default frontend is `frontend/src/StageOneApp.tsx`, and its backend entry point is `backend/main.py`. The earlier frontend and backend are retained as migration references.

Stage 1 readiness requires a working database connection and a successful model generation probe. With either unavailable, health reports `ready=false` and chat requests fail explicitly. Map, search, planning, and confirmed actions remain later stages.

## Run the Development Baseline

These instructions target **Windows PowerShell and the development branch**. Install Git, Node.js 20.19 or newer, and a Python installation with working `python -m pip`. The setup script uses uv to create an isolated Python 3.12.14 environment.

```powershell
git clone --branch codex/redesign-v1 --single-branch https://github.com/wangyux07-cmd/SOLOVIBE_APP.git
Set-Location SOLOVIBE_APP
powershell -NoProfile -File scripts/setup.ps1
```

Setup installs locked dependencies and copies environment templates only when local `.env` files are missing. **External API keys are not required to view the Stage 1 readiness screen.** Real conversation execution requires PostgreSQL and a model account that can complete generation requests. Run the explicit Stage 1 database migration only after reviewing the intended database connection.

Open two terminals at the repository root:

```powershell
# Terminal 1: backend
powershell -NoProfile -File scripts/dev.ps1 -Service backend
```

```powershell
# Terminal 2: frontend
powershell -NoProfile -File scripts/dev.ps1 -Service frontend
```

- Frontend: <http://127.0.0.1:5173>
- API documentation: <http://127.0.0.1:8000/docs>
- Health endpoint: <http://127.0.0.1:8000/api/v1/health>

The frontend development server proxies `/api` requests to the local backend. As external integrations are implemented, configure model, map, search, and database credentials in `backend/.env`. Frontend `VITE_*` variables are public configuration and must not contain secrets.

### Validation

```powershell
# Backend baseline tests, frontend type checking, and production build
powershell -NoProfile -File scripts/check.ps1

# Run after starting both services; the current browser configuration uses Microsoft Edge
npm run test:e2e --workspace frontend
```

Current local checks cover boundary behavior and unavailable-service UI; see [Stage 1 progress and integration limits](docs/STAGE1_PROGRESS_2026-10-12.md). They do not prove that live conversations or later planning features are ready.

## Design and Development Documents

The following documents are currently written in Chinese and are linked from the development branch. Delivery notes describe the state at the time they were written.

- [Original project review and redesign proposal](https://github.com/wangyux07-cmd/SOLOVIBE_APP/blob/codex/redesign-v1/docs/AI_AGENT_REDESIGN_PROPOSAL.md)
- [Redesigned Plan V1: architecture, state management, and delivery stages](https://github.com/wangyux07-cmd/SOLOVIBE_APP/blob/codex/redesign-v1/docs/AI_AGENT_REDESIGNED_PLAN_V1.md)
- [External tools and API integration plan](https://github.com/wangyux07-cmd/SOLOVIBE_APP/blob/codex/redesign-v1/docs/EXTERNAL_TOOLS_API_PLAN_V1.md)
- [Development baseline: setup, operation, and validation record](https://github.com/wangyux07-cmd/SOLOVIBE_APP/blob/codex/redesign-v1/docs/DEVELOPMENT_BASELINE.md)
