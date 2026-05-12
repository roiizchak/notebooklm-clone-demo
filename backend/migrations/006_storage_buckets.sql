-- Phase 1 migration 006: storage buckets + policies (sources only)

INSERT INTO storage.buckets (id, name, public)
VALUES ('sources', 'sources', false)
ON CONFLICT (id) DO NOTHING;

-- Folder pattern: {user_id}/{notebook_id}/{source_id}/{filename}

DROP POLICY IF EXISTS storage_sources_insert ON storage.objects;
CREATE POLICY storage_sources_insert ON storage.objects
  FOR INSERT WITH CHECK (
    bucket_id = 'sources'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );

DROP POLICY IF EXISTS storage_sources_select ON storage.objects;
CREATE POLICY storage_sources_select ON storage.objects
  FOR SELECT USING (
    bucket_id = 'sources'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );

DROP POLICY IF EXISTS storage_sources_delete ON storage.objects;
CREATE POLICY storage_sources_delete ON storage.objects
  FOR DELETE USING (
    bucket_id = 'sources'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );
