-- Phase 1 migration 002: notebooks + sources

CREATE TABLE IF NOT EXISTS public.notebooks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  emoji TEXT NOT NULL DEFAULT '📓',
  settings JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notebooks_user_id ON public.notebooks(user_id);

DROP TRIGGER IF EXISTS notebooks_set_updated_at ON public.notebooks;
CREATE TRIGGER notebooks_set_updated_at
  BEFORE UPDATE ON public.notebooks
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE IF NOT EXISTS public.sources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  notebook_id UUID NOT NULL REFERENCES public.notebooks(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('pdf','docx','url','youtube','text')),
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','processing','ready','failed')),
  file_path TEXT,
  original_filename TEXT,
  mime_type TEXT,
  file_size_bytes BIGINT,
  token_count INT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_guide JSONB,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sources_notebook_id ON public.sources(notebook_id);
CREATE INDEX IF NOT EXISTS idx_sources_status ON public.sources(status);

DROP TRIGGER IF EXISTS sources_set_updated_at ON public.sources;
CREATE TRIGGER sources_set_updated_at
  BEFORE UPDATE ON public.sources
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- Maintain notebooks.source_count.
CREATE OR REPLACE FUNCTION public.bump_notebook_source_count()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF (TG_OP = 'INSERT') THEN
    UPDATE public.notebooks
      SET source_count = source_count + 1, updated_at = NOW()
      WHERE id = NEW.notebook_id;
    RETURN NEW;
  ELSIF (TG_OP = 'DELETE') THEN
    UPDATE public.notebooks
      SET source_count = GREATEST(source_count - 1, 0), updated_at = NOW()
      WHERE id = OLD.notebook_id;
    RETURN OLD;
  END IF;
  RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS sources_count_ins ON public.sources;
CREATE TRIGGER sources_count_ins
  AFTER INSERT ON public.sources
  FOR EACH ROW EXECUTE FUNCTION public.bump_notebook_source_count();

DROP TRIGGER IF EXISTS sources_count_del ON public.sources;
CREATE TRIGGER sources_count_del
  AFTER DELETE ON public.sources
  FOR EACH ROW EXECUTE FUNCTION public.bump_notebook_source_count();
