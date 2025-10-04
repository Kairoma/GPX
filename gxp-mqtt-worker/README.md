# GXP MQTT Worker

ESP32S3-CAM Fleet Ingestion Middleware for Project X

## Overview

This worker service bridges your ESP32S3-CAM IoT device fleet with your Supabase database. It:

- **Listens to MQTT topics** from ESP32 devices publishing environmental data and camera images
- **Assembles chunked images** (devices send images in 1KB base64-encoded chunks)
- **Stores images** to Supabase Storage
- **Persists metadata** (captures, sensor readings, device status, errors) to Supabase
- **Handles retries** by requesting missing chunks via MQTT NACK
- **Sends ACK_OK** to devices when images are successfully stored

## Architecture

```
ESP32S3-CAM Devices
    │
    │ MQTT (TLS)
    │ Topics: ESP32CAM/{MAC}/data
    │          ESP32CAM/{MAC}/status
    │          ESP32CAM/{MAC}/ack
    ▼
┌─────────────────────┐
│  GXP MQTT Worker    │
│  (This Service)     │
│                     │
│  - Image Assembly   │
│  - Chunk Validation │
│  - Retry Logic      │
└─────────────────────┘
    │
    │ Supabase API (service_role)
    ▼
┌─────────────────────┐
│   Supabase          │
│                     │
│  - PostgreSQL       │
│    • captures       │
│    • sensor_readings│
│    • device_status  │
│    • device_errors  │
│    • devices        │
│                     │
│  - Storage          │
│    • gxp-captures   │
└─────────────────────┘
```

## ESP32 Firmware Message Formats

### Status Message
```json
{
  "device_id": "AABBCCDDEEFF",
  "status": "Alive",
  "pendingImg": 3
}
```
Published to: `ESP32CAM/{MAC}/status`

### Image Metadata
```json
{
  "device_id": "AABBCCDDEEFF",
  "capture_timeStamp": "2025-10-04T12:34:56Z",
  "image_name": "image_123.jpg",
  "image_size": 45678,
  "max_chunks_size": 1024,
  "total_chunk_count": 45,
  "location": "office_404",
  "error": 0,
  "temperature": 23.5,
  "humidity": 45.2,
  "pressure": 1013.25,
  "gas_resistance": 12345.67
}
```
Published to: `ESP32CAM/{MAC}/data`

### Image Chunk
```json
{
  "device_id": "AABBCCDDEEFF",
  "image_name": "image_123.jpg",
  "chunk_id": 0,
  "max_chunk_size": 1024,
  "payload": "<base64-encoded-bytes>"
}
```
Published to: `ESP32CAM/{MAC}/data`

### ACK_OK (Worker → Device)
```json
{
  "image_name": "image_123.jpg",
  "ACK_OK": {
    "next_wake_time": "5:30PM"
  }
}
```
Published to: `ESP32CAM/{MAC}/ack`

### NACK Missing Chunks (Worker → Device)
```json
{
  "image_name": "image_123.jpg",
  "missing_chunks": [5, 12, 23]
}
```
Published to: `ESP32CAM/{MAC}/ack`

## Quick Start (Local Development)

### Prerequisites
- Python 3.9+
- Supabase project with schema deployed
- MQTT broker credentials (HiveMQ Cloud)

### 1. Clone & Setup
```bash
cd /path/to/Project_X/gxp-mqtt-worker
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment
Edit `.env`:
```bash
# MQTT
MQTT_PASSWORD=your-actual-password

# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_ROLE=eyJhbGc...your-service-role-key
```

### 4. Run Locally
```bash
python app.py
```

You should see:
```
============================================================
GXP MQTT Worker - ESP32S3-CAM Fleet Ingestion
============================================================
MQTT Broker: 1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud:8883 (TLS: True)
Supabase: https://xxxxx.supabase.co
Storage Bucket: gxp-captures
============================================================
✓ MQTT connected successfully
✓ Subscribed to topics:
  - ESP32CAM/+/status
  - ESP32CAM/+/data
  - ESP32CAM/+/ack
✓ Worker started - processing messages...
```

## Deployment to Render

### 1. Push to GitHub
```bash
cd /path/to/Project_X
git add gxp-mqtt-worker/
git commit -m "Add MQTT worker middleware"
git push origin main
```

### 2. Create Render Service
1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **New** → **Background Worker**
3. Connect your GitHub repo (`Kairoma/GPX`)
4. Render will detect `render.yaml`
5. Click **Apply** to create the service

### 3. Set Environment Secrets
In Render dashboard, go to your worker's **Environment** tab and add:

| Key | Value |
|-----|-------|
| `MQTT_PASSWORD` | Your HiveMQ password |
| `SUPABASE_URL` | `https://xxxxx.supabase.co` |
| `SUPABASE_SERVICE_ROLE` | Your Supabase service role key |

### 4. Deploy
Click **Manual Deploy** → **Deploy latest commit**

Watch the logs for:
- ✓ MQTT connected successfully
- ✓ Subscribed to topics

## Supabase Setup

### 1. Create Storage Bucket
In Supabase Dashboard → Storage:
1. Click **New bucket**
2. Name: `gxp-captures`
3. **Public**: OFF (keep private)
4. Click **Create**

### 2. Run RLS Migration
In Supabase SQL Editor, run the migration from:
`gxp-mqtt-worker/supabase_rls_migration.sql`

This will:
- Enable RLS on device tables
- Create service_role policies (worker has full access)
- Create read-only policies for authenticated users

## Monitoring

### Check Device Status
```sql
-- Recent device heartbeats
select device_id, status, pending_count, created_at
from public.device_status
order by created_at desc
limit 20;
```

### Check Image Ingestion
```sql
-- Captures with storage paths
select device_id, device_capture_id, captured_at,
       image_bytes, total_chunks, ingest_status,
       storage_path, created_at
from public.captures
order by created_at desc
limit 20;
```

### Check Sensor Data
```sql
-- Recent sensor readings
select sr.device_id, sr.temperature_c, sr.humidity_pct,
       sr.pressure_hpa, sr.created_at
from public.sensor_readings sr
order by sr.created_at desc
limit 20;
```

### Check Errors
```sql
-- Recent errors
select device_id, capture_id, error_code,
       message, details, occurred_at
from public.device_errors
order by occurred_at desc
limit 50;
```

### Check MQTT Logs
```sql
-- Inbound/outbound messages
select topic, direction,
       payload->>'image_name' as image,
       payload->>'chunk_id' as chunk,
       received_at
from public.device_publish_log
order by received_at desc
limit 50;
```

## Testing Without Devices

You can test the worker using `mosquitto_pub`:

```bash
# Metadata
mosquitto_pub -h 1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud -p 8883 \
  --capath /etc/ssl/certs -u "BrainlyTesting" -P "YOUR_PASSWORD" \
  -t ESP32CAM/TESTMAC123/data \
  -m '{"device_id":"TESTMAC123","image_name":"test.jpg","image_size":4,"max_chunks_size":2,"total_chunk_count":2,"temperature":25.1,"humidity":45.0,"pressure":1010.2,"capture_timeStamp":"2025-10-04T12:00:00Z"}'

# Chunk 0 (JPEG SOI: 0xFF 0xD8)
mosquitto_pub -h 1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud -p 8883 \
  --capath /etc/ssl/certs -u "BrainlyTesting" -P "YOUR_PASSWORD" \
  -t ESP32CAM/TESTMAC123/data \
  -m '{"device_id":"TESTMAC123","image_name":"test.jpg","chunk_id":0,"max_chunk_size":1024,"payload":"/9g="}'

# Chunk 1 (JPEG EOI: 0xFF 0xD9)
mosquitto_pub -h 1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud -p 8883 \
  --capath /etc/ssl/certs -u "BrainlyTesting" -P "YOUR_PASSWORD" \
  -t ESP32CAM/TESTMAC123/data \
  -m '{"device_id":"TESTMAC123","image_name":"test.jpg","chunk_id":1,"max_chunk_size":1024,"payload":"/9k="}'
```

Expected result: ACK_OK published to `ESP32CAM/TESTMAC123/ack` and capture record in database with `ingest_status='stored'`.

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `MQTT_HOST` | HiveMQ Cloud | MQTT broker hostname |
| `MQTT_PORT` | 8883 | MQTT broker port (8883 for TLS) |
| `MQTT_TLS` | true | Enable TLS encryption |
| `MQTT_USERNAME` | BrainlyTesting | MQTT username |
| `MQTT_PASSWORD` | - | MQTT password (secret) |
| `TOPIC_PATTERN_DATA` | ESP32CAM/+/data | Data topic pattern |
| `TOPIC_PATTERN_STATUS` | ESP32CAM/+/status | Status topic pattern |
| `TOPIC_PATTERN_ACK` | ESP32CAM/+/ack | ACK topic pattern |
| `SUPABASE_URL` | - | Supabase project URL |
| `SUPABASE_SERVICE_ROLE` | - | Service role key (secret) |
| `SUPABASE_STORAGE_BUCKET` | gxp-captures | Storage bucket name |
| `CAPTURE_TIMEOUT_MS` | 60000 | Image assembly timeout (ms) |
| `RETRANSMIT_DELAY_MS` | 3000 | Delay before NACK (ms) |
| `RETRANSMIT_MAX` | 3 | Max retry attempts |
| `LOG_LEVEL` | INFO | Logging level |

## Troubleshooting

### Worker won't connect to MQTT
- Check `MQTT_PASSWORD` is set correctly
- Verify HiveMQ Cloud credentials
- Check firewall/network allows outbound 8883

### Images not appearing in Storage
- Verify `SUPABASE_SERVICE_ROLE` key is correct
- Check bucket name matches `SUPABASE_STORAGE_BUCKET`
- Check RLS policies are applied
- Look for errors in `device_errors` table

### Device not showing up
- Check device is publishing to correct topics
- Verify MAC address format (no colons)
- Check `device_publish_log` for inbound messages

### High memory usage
- Reduce `CAPTURE_TIMEOUT_MS` to clean up stale assemblies faster
- Check for devices sending duplicate metadata
- Monitor active assemblies (logged at DEBUG level)

## Error Codes

| Code | Severity | Description |
|------|----------|-------------|
| 2101 | error | Failed to parse JSON from data topic |
| 2102 | warn | Chunk missing payload field |
| 2103 | error | Base64 decode failed |
| 2200 | error | Assembly finalization failed |
| 2201 | error | Assembly timeout (missing chunks) |
| 2202 | warn | Declared size mismatch |
| 2203 | warn | Invalid JPEG signature |
| 2204 | error | Storage upload failed |
| 2205 | error | Capture DB update failed |

## License

Proprietary - Project X / GXP
