-- Runs at startup (CREATE ... IF NOT EXISTS, so it is safe to run again).
CREATE TABLE IF NOT EXISTS jobs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant      text NOT NULL,
  idem_key    text NOT NULL,             -- client-chosen; same key = same job, never a duplicate
  prompt      text NOT NULL,
  fail_times  int  NOT NULL DEFAULT 0,   -- demo switch: make the first N attempts fail
  status      text NOT NULL DEFAULT 'QUEUED',  -- QUEUED RUNNING RETRYING SUCCEEDED DEAD
  attempts    int  NOT NULL DEFAULT 0,
  result      jsonb,
  error       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant, idem_key)
);

-- Prompt versions are IMMUTABLE: a trigger refuses UPDATE and DELETE. A change = a new version.
CREATE TABLE IF NOT EXISTS prompt_versions (
  name        text NOT NULL,
  version     int  NOT NULL,
  template    text NOT NULL,          -- contains {text} where the input goes
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (name, version)
);
CREATE OR REPLACE FUNCTION forbid_change() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'prompt versions are immutable'; END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS prompt_immutable ON prompt_versions;
CREATE TRIGGER prompt_immutable BEFORE UPDATE OR DELETE ON prompt_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_change();

-- Tenants, API keys (only a SHA-256 hash is stored, never the key itself) and usage log.
CREATE TABLE IF NOT EXISTS tenants (
  name text PRIMARY KEY,
  tpm  int NOT NULL,        -- LLM tokens per minute
  conc int NOT NULL         -- max calls in flight
);
CREATE TABLE IF NOT EXISTS api_keys (
  key_hash text PRIMARY KEY,
  tenant   text NOT NULL REFERENCES tenants(name),
  prefix   text NOT NULL,   -- first chars, safe to show in a UI
  revoked  boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS usage (
  id            bigserial PRIMARY KEY,
  tenant        text NOT NULL,
  provider      text NOT NULL,       -- which provider answered, or 'cache'
  input_tokens  int NOT NULL,
  output_tokens int NOT NULL,
  latency_ms    int NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_tenant_time ON usage (tenant, created_at);
