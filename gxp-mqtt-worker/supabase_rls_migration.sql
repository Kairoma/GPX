-- ============================================
-- GXP MQTT Worker - RLS and Storage Setup
-- ============================================
-- Run this migration in Supabase SQL Editor AFTER creating the gxp-captures bucket
-- This enables Row Level Security and creates policies for the worker service

-- Enable RLS on device-related tables
ALTER TABLE public.captures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sensor_readings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_publish_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_errors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_command_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.device_sites ENABLE ROW LEVEL SECURITY;

-- ============================================
-- Service Role Policies (MQTT Worker)
-- ============================================
-- The worker uses the service_role key and needs full access

-- Captures: service_role full access
CREATE POLICY svc_all_captures ON public.captures
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- Sensor Readings: service_role full access
CREATE POLICY svc_all_sensor_readings ON public.sensor_readings
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- Device Status: service_role full access
CREATE POLICY svc_all_device_status ON public.device_status
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- Device Publish Log: service_role full access
CREATE POLICY svc_all_device_publish_log ON public.device_publish_log
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- Device Errors: service_role full access
CREATE POLICY svc_all_device_errors ON public.device_errors
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- Device Configs: service_role full access
CREATE POLICY svc_all_device_configs ON public.device_configs
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- Device Commands: service_role full access
CREATE POLICY svc_all_device_commands ON public.device_commands
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- Device Command Logs: service_role full access
CREATE POLICY svc_all_device_command_logs ON public.device_command_logs
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- Device Sites: service_role full access
CREATE POLICY svc_all_device_sites ON public.device_sites
  FOR ALL TO service_role
  USING (true)
  WITH CHECK (true);

-- ============================================
-- Authenticated User Policies (Web App)
-- ============================================
-- Users can read device data for their company

-- Captures: users can view captures from devices in their company
CREATE POLICY user_read_captures ON public.captures
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- Sensor Readings: users can view sensor data from their company's devices
CREATE POLICY user_read_sensor_readings ON public.sensor_readings
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- Device Status: users can view status of their company's devices
CREATE POLICY user_read_device_status ON public.device_status
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- Device Publish Log: users can view MQTT logs for their company's devices
CREATE POLICY user_read_device_publish_log ON public.device_publish_log
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- Device Errors: users can view errors from their company's devices
CREATE POLICY user_read_device_errors ON public.device_errors
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- Device Configs: users can view and update configs for their company's devices
CREATE POLICY user_read_device_configs ON public.device_configs
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

CREATE POLICY user_update_device_configs ON public.device_configs
  FOR UPDATE TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  )
  WITH CHECK (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- Device Commands: users can create and view commands for their company's devices
CREATE POLICY user_read_device_commands ON public.device_commands
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

CREATE POLICY user_insert_device_commands ON public.device_commands
  FOR INSERT TO authenticated
  WITH CHECK (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- Device Command Logs: users can view command logs for their company's devices
CREATE POLICY user_read_device_command_logs ON public.device_command_logs
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- Device Sites: users can view site assignments for their company's devices
CREATE POLICY user_read_device_sites ON public.device_sites
  FOR SELECT TO authenticated
  USING (
    device_id IN (
      SELECT d.device_id
      FROM public.devices d
      JOIN public.users u ON d.company_id = u.company_id
      WHERE u.id = auth.uid()
    )
  );

-- ============================================
-- Storage Policies
-- ============================================
-- Note: Storage bucket 'gxp-captures' should be created manually in UI as PRIVATE

-- Service role can upload/read/delete any file
CREATE POLICY "service_role_all_access"
ON storage.objects FOR ALL
TO service_role
USING (bucket_id = 'gxp-captures')
WITH CHECK (bucket_id = 'gxp-captures');

-- Authenticated users can read files from their company's devices
CREATE POLICY "user_read_captures"
ON storage.objects FOR SELECT
TO authenticated
USING (
  bucket_id = 'gxp-captures'
  AND (storage.foldername(name))[1] = 'captures'
  AND (storage.foldername(name))[2] IN (
    -- Extract device_hw_id from path: captures/{device_hw_id}/YYYY/MM/DD/image.jpg
    SELECT d.device_hw_id
    FROM public.devices d
    JOIN public.users u ON d.company_id = u.company_id
    WHERE u.id = auth.uid()
  )
);

-- ============================================
-- Indexes for Performance
-- ============================================
-- These help with the RLS policy queries

-- Index on devices.company_id for faster joins
CREATE INDEX IF NOT EXISTS idx_devices_company_id ON public.devices(company_id);

-- Index on captures.device_id for faster lookups
CREATE INDEX IF NOT EXISTS idx_captures_device_id ON public.captures(device_id);
CREATE INDEX IF NOT EXISTS idx_captures_device_capture_id ON public.captures(device_id, device_capture_id);
CREATE INDEX IF NOT EXISTS idx_captures_ingest_status ON public.captures(ingest_status);

-- Index on sensor_readings.device_id
CREATE INDEX IF NOT EXISTS idx_sensor_readings_device_id ON public.sensor_readings(device_id);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_capture_id ON public.sensor_readings(capture_id);

-- Index on device_status.device_id
CREATE INDEX IF NOT EXISTS idx_device_status_device_id ON public.device_status(device_id);
CREATE INDEX IF NOT EXISTS idx_device_status_created_at ON public.device_status(created_at DESC);

-- Index on device_errors.device_id
CREATE INDEX IF NOT EXISTS idx_device_errors_device_id ON public.device_errors(device_id);
CREATE INDEX IF NOT EXISTS idx_device_errors_capture_id ON public.device_errors(capture_id);

-- Index on device_publish_log.device_id
CREATE INDEX IF NOT EXISTS idx_device_publish_log_device_id ON public.device_publish_log(device_id);
CREATE INDEX IF NOT EXISTS idx_device_publish_log_received_at ON public.device_publish_log(received_at DESC);

-- ============================================
-- Verification Queries
-- ============================================
-- Run these to verify the migration was successful

-- Check RLS is enabled
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN (
    'captures', 'sensor_readings', 'device_status',
    'device_publish_log', 'device_errors', 'device_configs',
    'device_commands', 'device_command_logs', 'device_sites'
  );

-- Check policies exist
SELECT schemaname, tablename, policyname, roles, cmd, qual
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN (
    'captures', 'sensor_readings', 'device_status',
    'device_publish_log', 'device_errors', 'device_configs',
    'device_commands', 'device_command_logs', 'device_sites'
  )
ORDER BY tablename, policyname;

-- Check storage policies
SELECT name, definition
FROM pg_policies
WHERE schemaname = 'storage'
  AND tablename = 'objects';
