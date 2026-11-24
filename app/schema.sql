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
