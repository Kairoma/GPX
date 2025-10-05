-- Test #8 Verification Queries
-- Run these in Supabase SQL Editor to verify command queue system

-- 1. Check command status (should all be 'sent')
SELECT
  command_id,
  command_type,
  command_payload,
  status,
  sent_at,
  requested_at
FROM device_commands
WHERE device_id = '0283271b-d5c0-4a59-8f58-8f3fcb74d641'
ORDER BY requested_at DESC
LIMIT 10;

-- 2. Check device_command_logs (should have 5 'sent' events)
SELECT
  dcl.command_id,
  dcl.event_type,
  dcl.event_payload,
  dcl.created_at
FROM device_command_logs dcl
WHERE dcl.device_id = '0283271b-d5c0-4a59-8f58-8f3fcb74d641'
ORDER BY dcl.created_at DESC
LIMIT 10;
