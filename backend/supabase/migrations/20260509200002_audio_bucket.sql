-- Phase 2 migration 009: audio bucket + storage policies + bump sources size limit

-- New 'audio' bucket: 50 MB ceiling, private (signed-URL only)
INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES ('audio', 'audio', false, 52428800)
ON CONFLICT (id) DO UPDATE SET file_size_limit = EXCLUDED.file_size_limit;

-- Bump 'sources' bucket size limit to 50 MB so direct-upload signed URLs accept up to 50 MB.
UPDATE storage.buckets
SET file_size_limit = 52428800
WHERE id = 'sources';

-- Folder pattern (audio): {user_id}/{notebook_id}/{audio_id}.wav

DROP POLICY IF EXISTS storage_audio_insert ON storage.objects;
CREATE POLICY storage_audio_insert ON storage.objects
  FOR INSERT WITH CHECK (
    bucket_id = 'audio'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );

DROP POLICY IF EXISTS storage_audio_select ON storage.objects;
CREATE POLICY storage_audio_select ON storage.objects
  FOR SELECT USING (
    bucket_id = 'audio'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );

DROP POLICY IF EXISTS storage_audio_delete ON storage.objects;
CREATE POLICY storage_audio_delete ON storage.objects
  FOR DELETE USING (
    bucket_id = 'audio'
    AND auth.uid()::text = (storage.foldername(name))[1]
  );
