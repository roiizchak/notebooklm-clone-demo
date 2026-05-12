-- Phase 3.a migration 013: extend chat_messages with mode + research_report_id FK.
-- Hand-numbered copy. Timestamped sibling in supabase/migrations/.

ALTER TABLE public.chat_messages
  ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'chat'
    CHECK (mode IN ('chat', 'research')),
  ADD COLUMN IF NOT EXISTS research_report_id UUID
    REFERENCES public.research_reports(id) ON DELETE SET NULL;

-- Partial index: only research-linked messages are queryable by report id,
-- regular chat messages don't bloat the index.
CREATE INDEX IF NOT EXISTS idx_chat_messages_research_report
  ON public.chat_messages(research_report_id)
  WHERE research_report_id IS NOT NULL;
