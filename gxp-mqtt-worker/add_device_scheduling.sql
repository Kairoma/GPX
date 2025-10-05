-- Add device scheduling fields
-- Run this migration in Supabase SQL Editor

-- Add scheduling columns to devices table
ALTER TABLE public.devices
ADD COLUMN IF NOT EXISTS capture_interval_hours integer DEFAULT 12,
ADD COLUMN IF NOT EXISTS next_wake_at timestamp with time zone,
ADD COLUMN IF NOT EXISTS test_mode boolean DEFAULT false;

-- Add comments for documentation
COMMENT ON COLUMN public.devices.capture_interval_hours IS 'Hours between scheduled captures (default: 12, test mode: use 5-10 minutes via decimal)';
COMMENT ON COLUMN public.devices.next_wake_at IS 'Next scheduled wake time (UTC), dynamically updated by worker';
COMMENT ON COLUMN public.devices.test_mode IS 'When true, use short wake intervals for testing (5-10 min instead of hours)';

-- Set test mode for existing device
UPDATE public.devices
SET
  test_mode = true,
  capture_interval_hours = 1  -- Will be interpreted as minutes in test mode
WHERE device_hw_id = 'B8F862F9CFB8';

-- Create index for next_wake_at queries
CREATE INDEX IF NOT EXISTS idx_devices_next_wake ON public.devices(next_wake_at)
WHERE next_wake_at IS NOT NULL;

-- Helper function to calculate next wake time
CREATE OR REPLACE FUNCTION calculate_next_wake(
  current_time timestamp with time zone,
  interval_hours integer,
  is_test_mode boolean DEFAULT false
) RETURNS timestamp with time zone AS $$
BEGIN
  IF is_test_mode THEN
    -- Test mode: interval_hours is treated as MINUTES
    RETURN current_time + (interval_hours || ' minutes')::interval;
  ELSE
    -- Production mode: interval_hours is hours
    RETURN current_time + (interval_hours || ' hours')::interval;
  END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION calculate_next_wake IS 'Calculate next wake time based on interval and mode (test=minutes, prod=hours)';
