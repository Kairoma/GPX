-- Device Scheduling Setup using existing device_configs table
-- Run this in Supabase SQL Editor

-- NOTE: device_configs table already exists with:
-- - wakeup_time_1, wakeup_time_2: Scheduled wake times
-- - capture_per_day: Number of captures (default: 2)
-- - wakeup_window_sec: Wake window duration (default: 180s = 3min)

-- Add next_wake_at to devices table for dynamic scheduling
ALTER TABLE public.devices
ADD COLUMN IF NOT EXISTS next_wake_at timestamp with time zone;

-- Add test_mode flag to device_configs for development
ALTER TABLE public.device_configs
ADD COLUMN IF NOT EXISTS test_mode boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS test_interval_minutes integer DEFAULT 5
  CHECK (test_interval_minutes >= 1 AND test_interval_minutes <= 60);

-- Create index for next_wake_at queries
CREATE INDEX IF NOT EXISTS idx_devices_next_wake ON public.devices(next_wake_at)
WHERE next_wake_at IS NOT NULL;

-- Insert config for test device B8F862F9CFB8
INSERT INTO public.device_configs (device_id, test_mode, test_interval_minutes, capture_per_day, wakeup_window_sec)
SELECT
  device_id,
  true AS test_mode,
  1 AS test_interval_minutes,  -- 1 minute intervals for testing
  24 AS capture_per_day,        -- Allow frequent captures
  60 AS wakeup_window_sec       -- 1 minute wake window
FROM public.devices
WHERE device_hw_id = 'B8F862F9CFB8'
ON CONFLICT (device_id)
DO UPDATE SET
  test_mode = true,
  test_interval_minutes = 1,
  capture_per_day = 24,
  wakeup_window_sec = 60;

-- Comments
COMMENT ON COLUMN public.devices.next_wake_at IS 'Next scheduled wake time (UTC), dynamically updated by worker';
COMMENT ON COLUMN public.device_configs.test_mode IS 'When true, use test_interval_minutes instead of wakeup_time_1/2';
COMMENT ON COLUMN public.device_configs.test_interval_minutes IS 'Minutes between wakes in test mode (1-60)';
