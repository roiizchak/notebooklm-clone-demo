-- Phase 1 migration 005: Row-Level Security

ALTER TABLE public.profiles        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notebooks       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sources         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_chunks   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_logs      ENABLE ROW LEVEL SECURITY;

-- ---------- profiles ----------
DROP POLICY IF EXISTS profiles_self_select ON public.profiles;
CREATE POLICY profiles_self_select ON public.profiles
  FOR SELECT USING (auth.uid() = id);

DROP POLICY IF EXISTS profiles_self_update ON public.profiles;
CREATE POLICY profiles_self_update ON public.profiles
  FOR UPDATE USING (auth.uid() = id);

-- ---------- notebooks ----------
DROP POLICY IF EXISTS notebooks_self_select ON public.notebooks;
CREATE POLICY notebooks_self_select ON public.notebooks
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS notebooks_self_insert ON public.notebooks;
CREATE POLICY notebooks_self_insert ON public.notebooks
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS notebooks_self_update ON public.notebooks;
CREATE POLICY notebooks_self_update ON public.notebooks
  FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS notebooks_self_delete ON public.notebooks;
CREATE POLICY notebooks_self_delete ON public.notebooks
  FOR DELETE USING (auth.uid() = user_id);

-- ---------- sources ----------
DROP POLICY IF EXISTS sources_owned_select ON public.sources;
CREATE POLICY sources_owned_select ON public.sources
  FOR SELECT USING (
    notebook_id IN (
      SELECT id FROM public.notebooks WHERE user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS sources_owned_insert ON public.sources;
CREATE POLICY sources_owned_insert ON public.sources
  FOR INSERT WITH CHECK (
    notebook_id IN (
      SELECT id FROM public.notebooks WHERE user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS sources_owned_update ON public.sources;
CREATE POLICY sources_owned_update ON public.sources
  FOR UPDATE USING (
    notebook_id IN (
      SELECT id FROM public.notebooks WHERE user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS sources_owned_delete ON public.sources;
CREATE POLICY sources_owned_delete ON public.sources
  FOR DELETE USING (
    notebook_id IN (
      SELECT id FROM public.notebooks WHERE user_id = auth.uid()
    )
  );

-- ---------- source_chunks ----------
DROP POLICY IF EXISTS chunks_owned_select ON public.source_chunks;
CREATE POLICY chunks_owned_select ON public.source_chunks
  FOR SELECT USING (
    source_id IN (
      SELECT s.id FROM public.sources s
      JOIN public.notebooks n ON s.notebook_id = n.id
      WHERE n.user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS chunks_owned_insert ON public.source_chunks;
CREATE POLICY chunks_owned_insert ON public.source_chunks
  FOR INSERT WITH CHECK (
    source_id IN (
      SELECT s.id FROM public.sources s
      JOIN public.notebooks n ON s.notebook_id = n.id
      WHERE n.user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS chunks_owned_delete ON public.source_chunks;
CREATE POLICY chunks_owned_delete ON public.source_chunks
  FOR DELETE USING (
    source_id IN (
      SELECT s.id FROM public.sources s
      JOIN public.notebooks n ON s.notebook_id = n.id
      WHERE n.user_id = auth.uid()
    )
  );

-- ---------- chat_sessions ----------
DROP POLICY IF EXISTS chat_sessions_owned_select ON public.chat_sessions;
CREATE POLICY chat_sessions_owned_select ON public.chat_sessions
  FOR SELECT USING (
    notebook_id IN (
      SELECT id FROM public.notebooks WHERE user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS chat_sessions_owned_insert ON public.chat_sessions;
CREATE POLICY chat_sessions_owned_insert ON public.chat_sessions
  FOR INSERT WITH CHECK (
    notebook_id IN (
      SELECT id FROM public.notebooks WHERE user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS chat_sessions_owned_update ON public.chat_sessions;
CREATE POLICY chat_sessions_owned_update ON public.chat_sessions
  FOR UPDATE USING (
    notebook_id IN (
      SELECT id FROM public.notebooks WHERE user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS chat_sessions_owned_delete ON public.chat_sessions;
CREATE POLICY chat_sessions_owned_delete ON public.chat_sessions
  FOR DELETE USING (
    notebook_id IN (
      SELECT id FROM public.notebooks WHERE user_id = auth.uid()
    )
  );

-- ---------- chat_messages ----------
DROP POLICY IF EXISTS chat_messages_owned_select ON public.chat_messages;
CREATE POLICY chat_messages_owned_select ON public.chat_messages
  FOR SELECT USING (
    session_id IN (
      SELECT cs.id FROM public.chat_sessions cs
      JOIN public.notebooks n ON cs.notebook_id = n.id
      WHERE n.user_id = auth.uid()
    )
  );

DROP POLICY IF EXISTS chat_messages_owned_insert ON public.chat_messages;
CREATE POLICY chat_messages_owned_insert ON public.chat_messages
  FOR INSERT WITH CHECK (
    session_id IN (
      SELECT cs.id FROM public.chat_sessions cs
      JOIN public.notebooks n ON cs.notebook_id = n.id
      WHERE n.user_id = auth.uid()
    )
  );

-- ---------- usage_logs ----------
DROP POLICY IF EXISTS usage_logs_self_select ON public.usage_logs;
CREATE POLICY usage_logs_self_select ON public.usage_logs
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS usage_logs_self_insert ON public.usage_logs;
CREATE POLICY usage_logs_self_insert ON public.usage_logs
  FOR INSERT WITH CHECK (auth.uid() = user_id);
