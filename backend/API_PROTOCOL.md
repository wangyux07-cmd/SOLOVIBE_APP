# SoloVibe Running API Contract

> Applies to `Refactor` and the FastAPI app in [`main.py`](main.py). The earlier SSE and optional-thread proposal is preserved in [the historical protocol](API_PROTOCOL_LEGACY.md); it is not a description of the running API.

## Session and ownership

`POST /api/session` creates or reuses an anonymous browser session. The server sets an HTTP-only `solovibe_session` cookie. Every conversation, run, plan, and action read/write is scoped to its owner. The browser sends credentials with API requests. `GET /api/v1/health` reports service readiness; a configured key is not proof that the provider call succeeds.

JSON errors have the shape `{"error":{"code":"...","message":"..."},"stage":"v3-2"}`. Invalid input is rejected by FastAPI validation. Allowed CORS origins come from `CORS_ORIGINS`; browser-originated POSTs from other origins receive `ORIGIN_DENIED`.

## Conversation and planning

| Method and path | Purpose |
| --- | --- |
| `GET /api/conversations` | List owned conversations. |
| `POST /api/conversations` | Create an owned conversation. |
| `GET /api/conversations/{thread_id}` | Read messages, structured snapshot, current plan set, pending run, latest action, and saved plans. |
| `POST /api/chat` | Run the compiled LangGraph chat branch; synchronous JSON response. |
| `POST /api/conversations/{thread_id}/origin` | After a user-clicked browser location permission grant, convert WGS84 coordinates to Amap coordinates, reverse-geocode, and version the origin. |
| `GET /api/conversations/{thread_id}/plans` | Read the current plan set and context revision. |
| `GET /api/conversations/{thread_id}/runs/{run_id}/trace` | Read persisted node events for an owned run. |
| `POST /api/conversations/{thread_id}/runs/{run_id}/retry` | Retry a recoverable pending run. |

`POST /api/chat` requires a UUID `thread_id`, UUID `request_id`, nonblank `message` (up to 8000 characters), and nonnegative `expected_revision`. A repeated request ID must not create a second run. A stale revision is rejected. Planning may return `options_ready`, `clarification`, `no_options`, or `provider_unavailable`; the client must inspect `kind` and `evidence_status` rather than assuming every 200 response contains options.

A plan contains an Amap POI identity and address, independently queried outbound and return walking routes, optional Amap detail facts, optional Tavily leads, and explicit unknowns. Both routes carry duration, distance, coordinates, query time, and provider polyline points when supplied. `feasibility_checks.outbound_walk=pass` means the retrieved outbound route passed the time and walking bounds. `full_activity_time=pass` requires both routes plus a user-selected `desired_dwell_minutes`, with a fixed 10-minute buffer; otherwise it remains `unknown` or the plan is excluded if it exceeds the hard limit. `budget` and `open_now` remain `unknown` without further evidence. Amap `specialty_tags` are historical POI descriptors, not a live menu or current deal. Tavily hits mention the venue name but retain `identity_status=unverified`; they cannot establish the correct branch or a current price by themselves.

The origin request requires `request_id`, `expected_revision`, WGS84 `longitude`/`latitude`, and browser-reported `accuracy_m` (at most 300 m). The server uses Amap coordinate conversion and reverse geocoding before saving city, address, Amap coordinate, source, accuracy, and observation time. It requires the conversation owner, rejects stale revisions and active runs, and invalidates pending action confirmation. The browser requests location permission only after the user clicks. A browser-derived origin expires for planning and navigation after 30 minutes; the user can locate again or enter a place manually. Changing city or location text through chat clears the stored browser coordinate. The return destination defaults to the origin; `return_location_text` explicitly overrides it. `desired_dwell_minutes` is the user's plan, not an objective venue duration. The UI renders provider road polylines as a route sketch without a street basemap.

## V3 public-source evidence contract

`domain/evidence.py` defines `VenueIdentity`, `SourceObservation`, `VenueClaim`, `FeasibilityCheck`, and `ToolResult`. The additive tables `venue_identity`, `source_observation`, and `venue_claim` store public venue evidence independently of a user's conversation. Each observation has a source URL, scope, acquisition time, outcome, and optional short excerpt/hash. Each claim references one observation and carries field, value, scope, status, observation time, and optional expiry. A brand menu may be shown as a brand example; it must not pass a branch-specific constraint. Search leads never establish branch identity. A branch claim can affect a decision only if `check_branch_claim` verifies matching POI identity and source reference, successful acquisition, verified status, and freshness. Missing or stale facts remain `unknown`.

Plans now include `evidence_contract_version: 1` and optional `public_info`. `public_info.sources` carries observation IDs, HTTPS URLs, domain, extraction status, field scope, and retrieval time. Menu items and admission prices carry claim/observation IDs and an explicit `brand` or `branch` scope. The UI labels brand menu items as examples, never as a confirmed branch selection, current price, or availability. Only approved official HTTPS hosts are sent to Tavily Extract; every URL is checked in both `results` and `failed_results`, even on HTTP 200. The database stores a source domain, status, content length, SHA-256, and short excerpt, but not the extracted page body. A matched branch page must be specifically cataloged with its exact Amap POI ID and contain the full venue name plus a distinctive address. Current pilot coverage is one brand menu and zero branch-level menus/prices; no endpoint provides live inventory or a complete branch menu. Old saved snapshots without `public_info` remain readable.

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
