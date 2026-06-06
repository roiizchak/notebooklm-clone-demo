-- Migration 014: add WITH CHECK to UPDATE RLS policies, and tighten the
-- INSERT/UPDATE WITH CHECK on tables that carry BOTH user_id and notebook_id so
-- a row cannot be (re)assigned to a notebook the caller does not own (F5,
-- CWE-639). Backend uses the service_role key (bypasses RLS), so this is
-- defense-in-depth against direct/anon DB access, not the application layer.
--
-- The original UPDATE policies (005/008/012) specified only USING, leaving NEW
-- row values unconstrained. The original INSERT/UPDATE WITH CHECK on
-- study_materials / notes / audio_overviews / research_reports verified only
-- user_id, which let an owner set notebook_id to ANOTHER user's notebook (e.g.
-- occupying research_reports' one-active-per-notebook unique slot -> cross-tenant
-- DoS). Each policy below mirrors its USING predicate and, for notebook-scoped
-- tables, also pins notebook_id to a notebook owned by auth.uid().
--
-- Hand-numbered copy; the Supabase CLI applies the timestamped sibling in
-- supabase/migrations/.

-- Reusable predicate: notebook_id must belong to the calling user.
--   notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())

-- ---------- profiles (no notebook_id) ----------
DROP POLICY IF EXISTS profiles_self_update ON public.profiles;
CREATE POLICY profiles_self_update ON public.profiles
  FOR UPDATE USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id);

-- ---------- notebooks (row IS the notebook) ----------
DROP POLICY IF EXISTS notebooks_self_update ON public.notebooks;
CREATE POLICY notebooks_self_update ON public.notebooks
  FOR UPDATE USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

-- ---------- sources (notebook_id only) ----------
DROP POLICY IF EXISTS sources_owned_update ON public.sources;
CREATE POLICY sources_owned_update ON public.sources
  FOR UPDATE USING (
    notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  )
  WITH CHECK (
    notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

-- ---------- chat_sessions (notebook_id only) ----------
DROP POLICY IF EXISTS chat_sessions_owned_update ON public.chat_sessions;
CREATE POLICY chat_sessions_owned_update ON public.chat_sessions
  FOR UPDATE USING (
    notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  )
  WITH CHECK (
    notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

-- ---------- study_materials (user_id + notebook_id) ----------
DROP POLICY IF EXISTS study_materials_self_insert ON public.study_materials;
CREATE POLICY study_materials_self_insert ON public.study_materials
  FOR INSERT WITH CHECK (
    auth.uid() = user_id
    AND notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

DROP POLICY IF EXISTS study_materials_self_update ON public.study_materials;
CREATE POLICY study_materials_self_update ON public.study_materials
  FOR UPDATE USING (auth.uid() = user_id)
  WITH CHECK (
    auth.uid() = user_id
    AND notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

-- ---------- notes (user_id + notebook_id) ----------
DROP POLICY IF EXISTS notes_self_insert ON public.notes;
CREATE POLICY notes_self_insert ON public.notes
  FOR INSERT WITH CHECK (
    auth.uid() = user_id
    AND notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

DROP POLICY IF EXISTS notes_self_update ON public.notes;
CREATE POLICY notes_self_update ON public.notes
  FOR UPDATE USING (auth.uid() = user_id)
  WITH CHECK (
    auth.uid() = user_id
    AND notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

-- ---------- audio_overviews (user_id + notebook_id) ----------
DROP POLICY IF EXISTS audio_overviews_self_insert ON public.audio_overviews;
CREATE POLICY audio_overviews_self_insert ON public.audio_overviews
  FOR INSERT WITH CHECK (
    auth.uid() = user_id
    AND notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

DROP POLICY IF EXISTS audio_overviews_self_update ON public.audio_overviews;
CREATE POLICY audio_overviews_self_update ON public.audio_overviews
  FOR UPDATE USING (auth.uid() = user_id)
  WITH CHECK (
    auth.uid() = user_id
    AND notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

-- ---------- research_reports (user_id + notebook_id) ----------
DROP POLICY IF EXISTS research_reports_self_insert ON public.research_reports;
CREATE POLICY research_reports_self_insert ON public.research_reports
  FOR INSERT WITH CHECK (
    auth.uid() = user_id
    AND notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );

DROP POLICY IF EXISTS research_reports_self_update ON public.research_reports;
CREATE POLICY research_reports_self_update ON public.research_reports
  FOR UPDATE USING (auth.uid() = user_id)
  WITH CHECK (
    auth.uid() = user_id
    AND notebook_id IN (SELECT id FROM public.notebooks WHERE user_id = auth.uid())
  );
