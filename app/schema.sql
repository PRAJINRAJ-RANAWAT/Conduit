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
