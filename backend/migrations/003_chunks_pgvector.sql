-- Phase 1 migration 003: pgvector + source_chunks

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.source_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID NOT NULL REFERENCES public.sources(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  content TEXT NOT NULL,
  token_count INT NOT NULL,
  embedding vector(1536) NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.source_chunks
  DROP CONSTRAINT IF EXISTS chunks_embedding_dim;
ALTER TABLE public.source_chunks
  ADD CONSTRAINT chunks_embedding_dim CHECK (vector_dims(embedding) = 1536);

CREATE INDEX IF NOT EXISTS idx_chunks_source_id
  ON public.source_chunks(source_id);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
  ON public.source_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Top-k retrieval RPC. Bypasses RLS via SECURITY DEFINER but enforces
-- ownership through the notebook_id parameter (caller must verify
-- notebook ownership before invoking; backend always does).
CREATE OR REPLACE FUNCTION public.match_notebook_chunks(
  p_notebook_id UUID,
  p_query vector(1536),
  p_source_ids UUID[] DEFAULT NULL,
  p_k INT DEFAULT 8
)
RETURNS TABLE (
  chunk_id UUID,
  source_id UUID,
  source_name TEXT,
  content TEXT,
  metadata JSONB,
  similarity FLOAT
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    c.id AS chunk_id,
    c.source_id,
    s.name AS source_name,
    c.content,
    c.metadata,
    1 - (c.embedding <=> p_query) AS similarity
  FROM public.source_chunks c
  JOIN public.sources s ON s.id = c.source_id
  WHERE s.notebook_id = p_notebook_id
    AND s.status = 'ready'
    AND (p_source_ids IS NULL OR c.source_id = ANY(p_source_ids))
  ORDER BY c.embedding <=> p_query
  LIMIT p_k;
$$;
