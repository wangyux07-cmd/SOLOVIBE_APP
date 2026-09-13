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
CREATE INDEX IF NOT EXISTS conversations_owner ON solovibe_v1.conversations(owner_id);
CREATE INDEX IF NOT EXISTS node_events_run ON solovibe_v1.node_events(run_id, id);
REVOKE ALL ON SCHEMA solovibe_v1, solovibe_graph FROM PUBLIC;
