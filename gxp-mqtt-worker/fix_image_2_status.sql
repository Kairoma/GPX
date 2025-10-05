-- Fix the status for image_2.jpg that's stuck in "assembling"
-- This image is already successfully uploaded to S3

UPDATE public.captures
SET
  ingest_status = 'success',
  image_url = 'https://jycxolmevsvrxmeinxff.supabase.co/storage/v1/object/public/gxp-captures/captures/B8F862F9CFB8/2025/10/05/image_2.jpg'
WHERE capture_id = '5acfbc1b-6db3-4a06-abfe-3f5f9f3ff5d6'
AND ingest_status = 'assembling';

-- Verify the fix
SELECT
  capture_id,
  device_capture_id,
  ingest_status,
  storage_path,
  image_url,
  image_sha256
FROM captures
WHERE capture_id = '5acfbc1b-6db3-4a06-abfe-3f5f9f3ff5d6';
