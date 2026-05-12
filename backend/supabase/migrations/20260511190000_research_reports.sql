-- Phase 3.a migration 012: research_reports table for deep research mode.
-- See backend/migrations/012_research_reports.sql for the hand-numbered copy.

CREATE TABLE IF NOT EXISTS public.research_reports (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  notebook_id     UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id      UUID REFERENCES public.chat_sessions(id) ON DELETE SET NULL,
  question        TEXT NOT NULL,
  source_ids      UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  status          TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','researching','ready','failed','partial')),
  plan            JSONB,
  sections        JSONB NOT NULL DEFAULT '[]'::jsonb,
  content_md      TEXT,
  citations       JSONB NOT NULL DEFAULT '[]'::jsonb,
  model_plan      TEXT,
  model_sections  TEXT,
  model_stitch    TEXT,
  input_tokens    INT,
  output_tokens   INT,
  cost_usd        NUMERIC(12,6),
  error           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_research_reports_user_notebook
  ON public.research_reports(user_id, notebook_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_research_reports_status
  ON public.research_reports(status)
  WHERE status IN ('pending', 'researching');

CREATE UNIQUE INDEX IF NOT EXISTS uq_research_reports_one_active_per_notebook
  ON public.research_reports(notebook_id)
  WHERE status IN ('pending', 'researching');

DROP TRIGGER IF EXISTS research_reports_set_updated_at ON public.research_reports;
CREATE TRIGGER research_reports_set_updated_at
  BEFORE UPDATE ON public.research_reports
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.research_reports ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS research_reports_self_select ON public.research_reports;
CREATE POLICY research_reports_self_select ON public.research_reports
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS research_reports_self_insert ON public.research_reports;
CREATE POLICY research_reports_self_insert ON public.research_reports
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS research_reports_self_update ON public.research_reports;
CREATE POLICY research_reports_self_update ON public.research_reports
  FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS research_reports_self_delete ON public.research_reports;
CREATE POLICY research_reports_self_delete ON public.research_reports
  FOR DELETE USING (auth.uid() = user_id);
