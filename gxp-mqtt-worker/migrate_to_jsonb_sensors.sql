-- Migration: Consolidate sensor data into captures table using JSONB
-- This simplifies the schema and eliminates the need for JOINs

-- Step 1: Add sensor_data JSONB column to captures table
ALTER TABLE public.captures
ADD COLUMN IF NOT EXISTS sensor_data jsonb DEFAULT '{}';

-- Step 2: Migrate existing data from sensor_readings to captures.sensor_data
UPDATE public.captures c
SET sensor_data = jsonb_build_object(
  'temperature_c', sr.temperature_c,
  'humidity_pct', sr.humidity_pct,
  'pressure_hpa', sr.pressure_hpa,
  'gas_kohm', sr.gas_kohm,
  'captured_at', sr.captured_at
)
FROM public.sensor_readings sr
WHERE c.capture_id = sr.capture_id
  AND c.sensor_data = '{}';

-- Step 3: Create indexes for common sensor queries
-- GIN index for flexible JSON queries (e.g., searching multiple fields)
CREATE INDEX IF NOT EXISTS idx_captures_sensor_data_gin
ON public.captures USING GIN (sensor_data);

-- B-tree indexes for specific numeric queries (faster for ranges/comparisons)
CREATE INDEX IF NOT EXISTS idx_captures_temperature
ON public.captures (((sensor_data->>'temperature_c')::numeric))
WHERE sensor_data->>'temperature_c' IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_captures_humidity
ON public.captures (((sensor_data->>'humidity_pct')::numeric))
WHERE sensor_data->>'humidity_pct' IS NOT NULL;

-- Step 4: Add validation function for sensor data
CREATE OR REPLACE FUNCTION validate_sensor_data()
RETURNS TRIGGER AS $$
BEGIN
  -- Skip validation if sensor_data is empty
  IF NEW.sensor_data = '{}' THEN
    RETURN NEW;
  END IF;

  -- Validate temperature (-40 to 80°C is reasonable range)
  IF NEW.sensor_data ? 'temperature_c' THEN
    IF (NEW.sensor_data->>'temperature_c')::numeric < -40
       OR (NEW.sensor_data->>'temperature_c')::numeric > 80 THEN
      RAISE WARNING 'Temperature out of range: %', NEW.sensor_data->>'temperature_c';
    END IF;
  END IF;

  -- Validate humidity (0-100%)
  IF NEW.sensor_data ? 'humidity_pct' THEN
    IF (NEW.sensor_data->>'humidity_pct')::numeric < 0
       OR (NEW.sensor_data->>'humidity_pct')::numeric > 100 THEN
      RAISE WARNING 'Humidity out of range: %', NEW.sensor_data->>'humidity_pct';
    END IF;
  END IF;

  -- Validate pressure (reasonable atmospheric pressure: 800-1200 hPa)
  IF NEW.sensor_data ? 'pressure_hpa' THEN
    IF (NEW.sensor_data->>'pressure_hpa')::numeric < 800
       OR (NEW.sensor_data->>'pressure_hpa')::numeric > 1200 THEN
      RAISE WARNING 'Pressure out of range: %', NEW.sensor_data->>'pressure_hpa';
    END IF;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for validation
DROP TRIGGER IF EXISTS validate_sensor_data_trigger ON public.captures;
CREATE TRIGGER validate_sensor_data_trigger
BEFORE INSERT OR UPDATE ON public.captures
FOR EACH ROW
EXECUTE FUNCTION validate_sensor_data();

-- Step 5: Add comments for documentation
COMMENT ON COLUMN public.captures.sensor_data IS 'Environmental sensor data from BME680: temperature_c, humidity_pct, pressure_hpa, gas_kohm';

-- Step 6: Create helpful views for common queries
CREATE OR REPLACE VIEW captures_with_sensors AS
SELECT
  c.capture_id,
  c.device_id,
  c.device_capture_id,
  c.captured_at,
  c.image_url,
  c.storage_path,
  c.ingest_status,
  c.image_bytes,
  c.image_sha256,
  -- Extract sensor data as columns for easy querying
  (c.sensor_data->>'temperature_c')::numeric as temperature_c,
  (c.sensor_data->>'humidity_pct')::numeric as humidity_pct,
  (c.sensor_data->>'pressure_hpa')::numeric as pressure_hpa,
  (c.sensor_data->>'gas_kohm')::numeric as gas_kohm,
  c.sensor_data,
  c.created_at
FROM public.captures c;

COMMENT ON VIEW captures_with_sensors IS 'Captures with sensor data extracted as columns for easy querying';

-- Step 7: Verification queries (run after migration)
-- Uncomment to verify migration success:

-- Check migration success
-- SELECT
--   COUNT(*) as total_captures,
--   COUNT(*) FILTER (WHERE sensor_data != '{}') as with_sensor_data,
--   COUNT(*) FILTER (WHERE sensor_data = '{}') as without_sensor_data
-- FROM captures;

-- Check data quality
-- SELECT
--   device_capture_id,
--   captured_at,
--   sensor_data->>'temperature_c' as temp,
--   sensor_data->>'humidity_pct' as humidity
-- FROM captures
-- WHERE sensor_data != '{}'
-- ORDER BY captured_at DESC
-- LIMIT 10;

-- Step 8: Optional - Archive sensor_readings table (DO NOT DROP YET - keep as backup)
-- After confirming migration success for 1-2 weeks, you can drop the table:
-- DROP TABLE IF EXISTS public.sensor_readings CASCADE;

COMMENT ON TABLE public.sensor_readings IS 'DEPRECATED: Sensor data moved to captures.sensor_data. Keep as backup for 2 weeks then drop.';
