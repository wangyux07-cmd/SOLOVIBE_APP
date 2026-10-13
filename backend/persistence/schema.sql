CREATE SCHEMA IF NOT EXISTS solovibe_v1;
CREATE SCHEMA IF NOT EXISTS solovibe_graph;
CREATE TABLE IF NOT EXISTS solovibe_v1.sessions (
 owner_id uuid PRIMARY KEY, token_hash text UNIQUE NOT NULL,
 expires_at timestamptz NOT NULL DEFAULT now() + interval '30 days'
);
CREATE TABLE IF NOT EXISTS solovibe_v1.conversations (
 thread_id uuid PRIMARY KEY, owner_id uuid NOT NULL REFERENCES solovibe_v1.sessions,
 snapshot jsonb NOT NULL, active_run uuid, sequence bigint NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS solovibe_v1.runs (
 run_id uuid PRIMARY KEY, thread_id uuid NOT NULL REFERENCES solovibe_v1.conversations,
 request_id uuid NOT NULL, fingerprint text NOT NULL, message_id uuid NOT NULL,
 input_text text NOT NULL, base_snapshot jsonb NOT NULL,
 committed_snapshot jsonb, output jsonb, model_meta jsonb,
 status text NOT NULL DEFAULT 'running' CHECK(status IN ('running','failed','completed')),
 error_code text, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(thread_id, request_id)
);
CREATE TABLE IF NOT EXISTS solovibe_v1.messages (
 message_id uuid PRIMARY KEY, thread_id uuid NOT NULL REFERENCES solovibe_v1.conversations,
 run_id uuid NOT NULL REFERENCES solovibe_v1.runs,
 sequence bigint NOT NULL, role text NOT NULL CHECK(role IN ('user','assistant')),
 content text NOT NULL, UNIQUE(thread_id, sequence), UNIQUE(run_id, role)
);
CREATE TABLE IF NOT EXISTS solovibe_v1.node_events (
 id bigserial PRIMARY KEY, run_id uuid NOT NULL REFERENCES solovibe_v1.runs,
 node text NOT NULL, status text NOT NULL, elapsed_ms integer NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS solovibe_v1.rolling_summaries (
 thread_id uuid PRIMARY KEY REFERENCES solovibe_v1.conversations,
 summary_id uuid NOT NULL,
 revision integer NOT NULL CHECK(revision > 0),
 covered_until_sequence bigint NOT NULL CHECK(covered_until_sequence > 0),
 source_first_sequence bigint NOT NULL,
 source_last_sequence bigint NOT NULL,
 source_digest text NOT NULL,
 based_on_context_revision integer NOT NULL,
 schema_version integer NOT NULL DEFAULT 1,
 content jsonb NOT NULL,
 token_estimate integer NOT NULL,
 generated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS solovibe_v1.plan_sets (
 run_id uuid PRIMARY KEY REFERENCES solovibe_v1.runs,
 thread_id uuid NOT NULL REFERENCES solovibe_v1.conversations,
 context_revision integer NOT NULL,
 payload jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS solovibe_v1.actions (
 action_id uuid PRIMARY KEY,
 thread_id uuid NOT NULL REFERENCES solovibe_v1.conversations,
 owner_id uuid NOT NULL REFERENCES solovibe_v1.sessions,
 plan_set_id uuid NOT NULL REFERENCES solovibe_v1.plan_sets(run_id),
 plan_id text NOT NULL,
 context_revision integer NOT NULL,
 kind text NOT NULL CHECK(kind IN ('save','navigate')),
 request_id uuid NOT NULL,
 fingerprint text NOT NULL,
 proposal_version integer NOT NULL DEFAULT 1,
 proposal_digest text NOT NULL,
 plan_snapshot jsonb NOT NULL,
 context_snapshot jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('awaiting_confirmation','authorized','rejected','invalidated','claimed','completed')),
 decision_request_id uuid,
 receipt jsonb,
 handoff_requested_at timestamptz,
 handoff_request_id uuid,
 expires_at timestamptz NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(thread_id, request_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS actions_one_pending ON solovibe_v1.actions(thread_id)
 WHERE status IN ('awaiting_confirmation','authorized','claimed');
ALTER TABLE solovibe_v1.actions ADD COLUMN IF NOT EXISTS handoff_requested_at timestamptz;
ALTER TABLE solovibe_v1.actions ADD COLUMN IF NOT EXISTS handoff_request_id uuid;
CREATE TABLE IF NOT EXISTS solovibe_v1.saved_plans (
 action_id uuid PRIMARY KEY REFERENCES solovibe_v1.actions,
 thread_id uuid NOT NULL REFERENCES solovibe_v1.conversations,
 plan_snapshot jsonb NOT NULL,
 saved_at timestamptz NOT NULL DEFAULT now()
);
-- V3 public venue evidence contains no user location or conversation content.
CREATE TABLE IF NOT EXISTS solovibe_v1.venue_identity (
 venue_id uuid PRIMARY KEY,
 amap_poi_id text UNIQUE NOT NULL,
 name text NOT NULL, city text NOT NULL, address text NOT NULL,
 amap_coordinate text NOT NULL,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS solovibe_v1.source_observation (
 observation_id uuid PRIMARY KEY,
 venue_id uuid REFERENCES solovibe_v1.venue_identity,
 kind text NOT NULL CHECK(kind IN ('map_api','official_site','authorized_api','merchant_direct','search_lead')),
 outcome text NOT NULL CHECK(outcome IN ('success','empty','forbidden','timeout','invalid_response','identity_conflict','stale')),
 scope text NOT NULL CHECK(scope IN ('branch','brand','area')),
 source_url text NOT NULL,
 observed_at timestamptz NOT NULL,
 content_sha256 text,
 evidence_excerpt varchar(400),
 CHECK(scope <> 'branch' OR venue_id IS NOT NULL),
 CHECK(kind <> 'search_lead' OR scope <> 'branch')
);
ALTER TABLE solovibe_v1.source_observation ADD COLUMN IF NOT EXISTS source_domain text;
ALTER TABLE solovibe_v1.source_observation ADD COLUMN IF NOT EXISTS extract_status text;
ALTER TABLE solovibe_v1.source_observation ADD COLUMN IF NOT EXISTS field_scope text;
ALTER TABLE solovibe_v1.source_observation ADD COLUMN IF NOT EXISTS content_length integer;
CREATE TABLE IF NOT EXISTS solovibe_v1.venue_claim (
 claim_id uuid PRIMARY KEY,
 observation_id uuid NOT NULL REFERENCES solovibe_v1.source_observation,
 venue_id uuid REFERENCES solovibe_v1.venue_identity,
 field text NOT NULL,
 value jsonb,
 unit text,
 scope text NOT NULL CHECK(scope IN ('branch','brand','area')),
 status text NOT NULL CHECK(status IN ('verified','indicative','unknown','stale','conflict')),
 observed_at timestamptz NOT NULL,
 valid_until timestamptz,
 CHECK(scope <> 'branch' OR venue_id IS NOT NULL),
 CHECK(field NOT IN ('offer','open_now','availability') OR status <> 'verified' OR valid_until IS NOT NULL)
);
ALTER TABLE solovibe_v1.venue_claim ALTER COLUMN value DROP NOT NULL;
CREATE INDEX IF NOT EXISTS conversations_owner ON solovibe_v1.conversations(owner_id);
CREATE INDEX IF NOT EXISTS node_events_run ON solovibe_v1.node_events(run_id, id);
CREATE INDEX IF NOT EXISTS plan_sets_thread ON solovibe_v1.plan_sets(thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS actions_thread ON solovibe_v1.actions(thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS source_observation_venue_time ON solovibe_v1.source_observation(venue_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS venue_claim_venue_field ON solovibe_v1.venue_claim(venue_id, field, observed_at DESC);
REVOKE ALL ON SCHEMA solovibe_v1, solovibe_graph FROM PUBLIC;
