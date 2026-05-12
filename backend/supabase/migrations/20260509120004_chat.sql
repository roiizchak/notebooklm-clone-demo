-- Phase 1 migration 004: chat_sessions + chat_messages + usage_logs

CREATE TABLE IF NOT EXISTS public.chat_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
  title TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_notebook_id
  ON public.chat_sessions(notebook_id);

DROP TRIGGER IF EXISTS chat_sessions_set_updated_at ON public.chat_sessions;
CREATE TRIGGER chat_sessions_set_updated_at
  BEFORE UPDATE ON public.chat_sessions
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE IF NOT EXISTS public.chat_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL,
  citations JSONB NOT NULL DEFAULT '[]'::jsonb,
  source_ids_used JSONB NOT NULL DEFAULT '[]'::jsonb,
  model_used TEXT,
  input_tokens INT,
  output_tokens INT,
  cost_usd NUMERIC(12,6),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
  ON public.chat_messages(session_id);

-- Touch chat_sessions.updated_at whenever a message is inserted (so the
-- session sort by recency works).
CREATE OR REPLACE FUNCTION public.touch_chat_session()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  UPDATE public.chat_sessions
  SET updated_at = NOW()
  WHERE id = NEW.session_id;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS chat_messages_touch_session ON public.chat_messages;
CREATE TRIGGER chat_messages_touch_session
  AFTER INSERT ON public.chat_messages
  FOR EACH ROW EXECUTE FUNCTION public.touch_chat_session();

CREATE TABLE IF NOT EXISTS public.usage_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  notebook_id UUID REFERENCES public.notebooks(id) ON DELETE SET NULL,
  operation_type TEXT NOT NULL,
  model_used TEXT,
  input_tokens INT,
  output_tokens INT,
  cost_usd NUMERIC(12,6),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id
  ON public.usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at
  ON public.usage_logs(created_at);
