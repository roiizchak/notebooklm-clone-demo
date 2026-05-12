-- 010: prevent two simultaneous active audio_overviews per notebook.
-- A new generate request must wait for the existing pending/generating row
-- to settle (succeed -> ready, fail -> failed) before another can be queued.

CREATE UNIQUE INDEX IF NOT EXISTS uq_audio_overviews_one_active_per_notebook
  ON public.audio_overviews (notebook_id)
  WHERE status IN ('pending', 'generating');
