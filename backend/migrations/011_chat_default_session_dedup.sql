-- B-COR-10: partial UNIQUE index so concurrent first-message POSTs collide
-- at the DB layer instead of silently creating duplicate default sessions.
-- A session with title IS NULL is the auto-created default for its notebook.

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_sessions_default_per_notebook
  ON public.chat_sessions (notebook_id)
  WHERE title IS NULL;
