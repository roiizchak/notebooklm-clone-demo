-- Phase 2 migration 008: study_materials + notes + audio_overviews + RLS

-- ---------- study_materials ----------
CREATE TABLE IF NOT EXISTS public.study_materials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('flashcards','quiz','study_guide','faq')),
  payload JSONB NOT NULL,
  source_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  model_used TEXT NOT NULL,
  cost_usd NUMERIC(10,6),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (notebook_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_study_materials_user_notebook
  ON public.study_materials(user_id, notebook_id);

DROP TRIGGER IF EXISTS study_materials_set_updated_at ON public.study_materials;
CREATE TRIGGER study_materials_set_updated_at
  BEFORE UPDATE ON public.study_materials
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ---------- notes ----------
CREATE TABLE IF NOT EXISTS public.notes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('written','saved_response')),
  title TEXT,
  content TEXT NOT NULL,
  tags JSONB NOT NULL DEFAULT '[]'::jsonb,
  is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
  original_message_id UUID REFERENCES public.chat_messages(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_user_notebook_pinned
  ON public.notes(user_id, notebook_id, is_pinned DESC, updated_at DESC);

DROP TRIGGER IF EXISTS notes_set_updated_at ON public.notes;
CREATE TRIGGER notes_set_updated_at
  BEFORE UPDATE ON public.notes
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ---------- audio_overviews ----------
CREATE TABLE IF NOT EXISTS public.audio_overviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','generating','ready','failed')),
  target_minutes INT NOT NULL CHECK (target_minutes IN (5,10,15)),
  custom_instructions TEXT,
  source_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  script TEXT,
  audio_path TEXT,
  duration_seconds INT,
  error TEXT,
  cost_usd NUMERIC(10,6),
  model_script TEXT,
  model_tts TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audio_overviews_user_notebook
  ON public.audio_overviews(user_id, notebook_id, created_at DESC);

DROP TRIGGER IF EXISTS audio_overviews_set_updated_at ON public.audio_overviews;
CREATE TRIGGER audio_overviews_set_updated_at
  BEFORE UPDATE ON public.audio_overviews
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ---------- RLS ----------
ALTER TABLE public.study_materials  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notes            ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audio_overviews  ENABLE ROW LEVEL SECURITY;

-- study_materials
DROP POLICY IF EXISTS study_materials_self_select ON public.study_materials;
CREATE POLICY study_materials_self_select ON public.study_materials
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS study_materials_self_insert ON public.study_materials;
CREATE POLICY study_materials_self_insert ON public.study_materials
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS study_materials_self_update ON public.study_materials;
CREATE POLICY study_materials_self_update ON public.study_materials
  FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS study_materials_self_delete ON public.study_materials;
CREATE POLICY study_materials_self_delete ON public.study_materials
  FOR DELETE USING (auth.uid() = user_id);

-- notes
DROP POLICY IF EXISTS notes_self_select ON public.notes;
CREATE POLICY notes_self_select ON public.notes
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS notes_self_insert ON public.notes;
CREATE POLICY notes_self_insert ON public.notes
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS notes_self_update ON public.notes;
CREATE POLICY notes_self_update ON public.notes
  FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS notes_self_delete ON public.notes;
CREATE POLICY notes_self_delete ON public.notes
  FOR DELETE USING (auth.uid() = user_id);

-- audio_overviews
DROP POLICY IF EXISTS audio_overviews_self_select ON public.audio_overviews;
CREATE POLICY audio_overviews_self_select ON public.audio_overviews
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS audio_overviews_self_insert ON public.audio_overviews;
CREATE POLICY audio_overviews_self_insert ON public.audio_overviews
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS audio_overviews_self_update ON public.audio_overviews;
CREATE POLICY audio_overviews_self_update ON public.audio_overviews
  FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS audio_overviews_self_delete ON public.audio_overviews;
CREATE POLICY audio_overviews_self_delete ON public.audio_overviews
  FOR DELETE USING (auth.uid() = user_id);
