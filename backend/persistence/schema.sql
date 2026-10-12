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
CREATE INDEX IF NOT EXISTS conversations_owner ON solovibe_v1.conversations(owner_id);
CREATE INDEX IF NOT EXISTS node_events_run ON solovibe_v1.node_events(run_id, id);
CREATE INDEX IF NOT EXISTS plan_sets_thread ON solovibe_v1.plan_sets(thread_id, created_at DESC);
REVOKE ALL ON SCHEMA solovibe_v1, solovibe_graph FROM PUBLIC;
