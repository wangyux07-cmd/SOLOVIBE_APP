# SoloVibe Running API Contract

> Applies to `Refactor` and the FastAPI app in [`main.py`](main.py). The earlier SSE and optional-thread proposal is preserved in [the historical protocol](API_PROTOCOL_LEGACY.md); it is not a description of the running API.

## Session and ownership

`POST /api/session` creates or reuses an anonymous browser session. The server sets an HTTP-only `solovibe_session` cookie. Every conversation, run, plan, and action read/write is scoped to its owner. The browser sends credentials with API requests. `GET /api/v1/health` reports service readiness; a configured key is not proof that the provider call succeeds.

JSON errors have the shape `{"error":{"code":"...","message":"..."},"stage":"stage4"}`. Invalid input is rejected by FastAPI validation. Allowed CORS origins come from `CORS_ORIGINS`; browser-originated POSTs from other origins receive `ORIGIN_DENIED`.

## Conversation and planning

| Method and path | Purpose |
| --- | --- |
| `GET /api/conversations` | List owned conversations. |
| `POST /api/conversations` | Create an owned conversation. |
| `GET /api/conversations/{thread_id}` | Read messages, structured snapshot, current plan set, pending run, latest action, and saved plans. |
| `POST /api/chat` | Run the compiled LangGraph chat branch; synchronous JSON response. |
| `GET /api/conversations/{thread_id}/plans` | Read the current plan set and context revision. |
| `GET /api/conversations/{thread_id}/runs/{run_id}/trace` | Read persisted node events for an owned run. |
| `POST /api/conversations/{thread_id}/runs/{run_id}/retry` | Retry a recoverable pending run. |

`POST /api/chat` requires a UUID `thread_id`, UUID `request_id`, nonblank `message` (up to 8000 characters), and nonnegative `expected_revision`. A repeated request ID must not create a second run. A stale revision is rejected. Planning may return `options_ready`, `clarification`, `no_options`, or `provider_unavailable`; the client must inspect `kind` and `evidence_status` rather than assuming every 200 response contains options.

A plan contains an Amap POI identity and address, an outbound walking-route observation with origin and destination coordinates, optional Amap detail facts, optional Tavily leads, and explicit unknowns. `feasibility_checks.outbound_walk=pass` means the retrieved **outbound route** passed the time and walking bounds. `full_activity_time`, `budget`, and `open_now` remain `unknown` without further evidence. Amap `specialty_tags` are historical POI descriptors, not a live menu or current deal. Tavily hits mention the venue name but retain `identity_status=unverified`; they cannot establish the correct branch or a current price by themselves.

## Confirmed actions

| Method and path | Purpose |
| --- | --- |
| `POST /api/conversations/{thread_id}/actions` | Prepare a version-bound `save` or `navigate` proposal for a selected current `plan_set_id` and `plan_id`. |
| `GET /api/actions/{action_id}` | Read an owned action. |
| `POST /api/actions/{action_id}/decision` | Approve or reject using request ID, proposal version, and SHA-256 digest. |
| `POST /api/actions/{action_id}/recover` | Resume a confirmed action from its durable LangGraph interrupt. |
| `POST /api/actions/{action_id}/handoff` | Record one request to open a prepared navigation link. |

Preparation never executes the action. A confirmed save writes one immutable saved-plan snapshot. A confirmed navigation action rechecks the same POI, geocodes the origin again, and obtains a fresh walking route before returning `navigation_handoff_ready` with an Amap URI. The URI and `handoff_requested_at` do not prove that the map app opened, the user departed, or the user arrived. New chat input invalidates an unrelated pending confirmation before it proceeds.

## Inactive historical routes

`POST /api/v1/stream_chat`, `POST /api/v1/threads/{thread_id}/resume`, and `GET /api/v2/wander-plans` return `FEATURE_NOT_IMPLEMENTED`. The supported interface is the JSON API above. Live schema details and validation rules are also available from the running app at `/openapi.json` and `/docs`.
