# GXP MQTT Worker - Deployment Guide

## 🎯 What We Built

A production-ready MQTT middleware service that:
- ✅ Receives chunked images + sensor data from ESP32S3-CAM devices via MQTT
- ✅ Assembles 1KB chunks into complete JPEG images
- ✅ Uploads images to Supabase Storage
- ✅ Persists metadata to Supabase PostgreSQL
- ✅ Handles retries with NACK/ACK protocol
- ✅ Logs all device activity for debugging

## 📁 Project Structure

```
gxp-mqtt-worker/
├── app.py                      # Main worker application
├── requirements.txt            # Python dependencies
├── render.yaml                 # Render deployment config
├── .env.example                # Environment template
├── .gitignore                  # Git ignore rules
├── README.md                   # Full documentation
├── supabase_rls_migration.sql  # Database security policies
├── test_mqtt.py                # Test script (simulates ESP32)
└── DEPLOYMENT_GUIDE.md         # This file
```

## 🚀 Deployment Steps

### Step 1: Supabase Setup (One-Time)

#### 1A. Create Storage Bucket
1. Go to your Supabase project → **Storage**
2. Click **New bucket**
3. Name: `gxp-captures`
4. **Public**: OFF (keep private)
5. Click **Create bucket**

#### 1B. Run RLS Migration
1. Go to **SQL Editor** in Supabase
2. Open `supabase_rls_migration.sql`
3. Copy entire contents and paste into SQL Editor
4. Click **Run**
5. Verify success with the verification queries at the bottom

**What this does:**
- Enables Row Level Security on all device tables
- Creates policies allowing the worker (service_role) full access
- Creates policies allowing web app users to read their company's device data
- Adds indexes for performance
- Sets up storage bucket policies

### Step 2: Push to GitHub

```bash
cd /Users/thefinalmachine/dev/Project_X

# Add all worker files
git add gxp-mqtt-worker/

# Commit
git commit -m "feat: Add MQTT middleware worker for ESP32 fleet ingestion"

# Push to your repo
git push origin main  # or 'master' depending on your default branch
```

### Step 3: Deploy to Render

#### 3A. Create Worker Service
1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **New** → **Background Worker**
3. Connect your GitHub repository: `Kairoma/GPX`
4. Render will auto-detect `render.yaml`
5. Click **Apply**

#### 3B. Set Environment Secrets
In the Render dashboard, go to your worker's **Environment** tab.

Add these **secret** variables (do NOT commit these to git):

| Key | Value | Where to Find It |
|-----|-------|------------------|
| `MQTT_PASSWORD` | `BrainlyTest@1234` | Your HiveMQ Cloud password |
| `SUPABASE_URL` | `https://xxxxx.supabase.co` | Supabase → Project Settings → API |
| `SUPABASE_SERVICE_ROLE` | `eyJhbGc...` | Supabase → Project Settings → API → service_role key |

**IMPORTANT:** Use the **service_role** key, NOT the anon key!

#### 3C. Deploy
1. Click **Manual Deploy** → **Deploy latest commit**
2. Watch the logs for:
   ```
   ✓ MQTT connected successfully
   ✓ Subscribed to topics:
     - ESP32CAM/+/status
     - ESP32CAM/+/data
     - ESP32CAM/+/ack
   ✓ Worker started - processing messages...
   ```

If you see those messages, **you're live!** 🎉

### Step 4: Test Locally (Optional but Recommended)

Before deploying, you can test locally:

```bash
cd /Users/thefinalmachine/dev/Project_X/gxp-mqtt-worker

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your actual credentials
nano .env  # or use your preferred editor

# Run the worker
python app.py
```

In another terminal, run the test script:
```bash
source venv/bin/activate
python test_mqtt.py
```

You should see:
1. Test script publishes metadata + 2 chunks
2. Worker logs show assembly completion
3. Test script receives ACK_OK
4. Check Supabase:
   - Storage bucket has `captures/AABBCCDDEEFF/2025/10/04/test_image_001.jpg`
   - `captures` table has a row with `ingest_status='stored'`
   - `sensor_readings` table has environmental data

## 🔍 Verification Queries

Run these in Supabase SQL Editor to check ingestion:

```sql
-- Recent device activity
SELECT device_id, status, pending_count, created_at
FROM public.device_status
ORDER BY created_at DESC
LIMIT 20;

-- Captured images
SELECT device_id, device_capture_id, captured_at,
       image_bytes, total_chunks, ingest_status,
       storage_path, created_at
FROM public.captures
ORDER BY created_at DESC
LIMIT 20;

-- Sensor readings
SELECT sr.device_id, sr.temperature_c, sr.humidity_pct,
       sr.pressure_hpa, sr.created_at
FROM public.sensor_readings sr
ORDER BY sr.created_at DESC
LIMIT 20;

-- Any errors?
SELECT device_id, error_code, message, details, occurred_at
FROM public.device_errors
ORDER BY occurred_at DESC
LIMIT 20;

-- MQTT message log
SELECT topic, direction,
       payload->>'image_name' as image,
       received_at
FROM public.device_publish_log
ORDER BY received_at DESC
LIMIT 50;
```

## 📊 Monitoring in Production

### Render Logs
- Go to your worker in Render Dashboard
- Click **Logs** tab
- You'll see real-time logs of:
  - Device connections
  - Image assemblies
  - Storage uploads
  - Errors

### Supabase Dashboard
- **Storage** → `gxp-captures` → Browse uploaded images
- **Database** → Use SQL Editor to run verification queries
- **Logs** → See database queries and errors

### Key Metrics to Watch
- **Capture success rate**: `ingest_status='stored'` vs `'failed'`
- **Assembly timeouts**: Check `device_errors` for code 2201
- **Storage failures**: Check `device_errors` for code 2204
- **MQTT connection stability**: Watch Render logs for reconnections

## 🐛 Troubleshooting

### Worker won't start on Render
**Symptom:** Build succeeds but worker crashes immediately

**Check:**
1. Environment variables are set correctly
2. `SUPABASE_SERVICE_ROLE` is the **service_role** key (not anon)
3. MQTT credentials are correct

**Fix:** Check Render logs for the specific error

### Worker connects but devices aren't showing up
**Symptom:** Worker logs show "✓ MQTT connected" but no device activity

**Check:**
1. ESP32 devices are publishing to correct topics: `ESP32CAM/{MAC}/data`
2. Device MAC addresses have no colons (should be `AABBCCDDEEFF`, not `AA:BB:CC:DD:EE:FF`)
3. Run this query to see if ANY messages are being received:
   ```sql
   SELECT * FROM device_publish_log ORDER BY received_at DESC LIMIT 10;
   ```

**Fix:**
- If table is empty: ESP32s aren't publishing to the broker
- If table has data: Worker is receiving messages (check `device_errors` table)

### Images aren't appearing in Storage
**Symptom:** `captures` table has rows but no `storage_path`

**Check:**
1. Storage bucket `gxp-captures` exists and is **private** (not public)
2. RLS migration was run successfully
3. Check `device_errors` table for code 2204 (storage upload failed)

**Fix:**
```sql
-- Check for storage upload errors
SELECT device_id, message, details, occurred_at
FROM device_errors
WHERE error_code = 2204
ORDER BY occurred_at DESC
LIMIT 10;
```

### High memory usage
**Symptom:** Render worker using lots of memory or OOM crashes

**Cause:** Too many incomplete assemblies held in memory

**Fix:**
1. Reduce `CAPTURE_TIMEOUT_MS` in Render environment to clean up faster
2. Check for devices repeatedly sending metadata without chunks
3. Monitor active assemblies (set `LOG_LEVEL=DEBUG` temporarily)

## 🔐 Security Notes

### What's Secure
- ✅ MQTT connection uses TLS encryption (port 8883)
- ✅ Storage bucket is **private** (requires signed URLs)
- ✅ Service role key used by worker only (not exposed to clients)
- ✅ Row Level Security enforces company isolation
- ✅ No secrets in git (`.env` is ignored)

### Best Practices
1. **Never commit** `.env` file
2. **Rotate** MQTT and Supabase credentials periodically
3. **Monitor** `device_publish_log` for suspicious activity
4. **Limit** service_role key to Render environment only

## 📈 Next Steps

### 1. Add Device Management UI
Build a React component to:
- View device list with last_seen_at
- View device status (battery, RSSI, uptime)
- Send commands to devices (via `device_commands` table)
- View image gallery with thumbnails

### 2. Add Alerts
Set up monitoring for:
- Devices offline > 24 hours
- High error rates (> 10% failed captures)
- Low battery warnings
- Storage quota approaching limit

### 3. Add Analytics
Build dashboards showing:
- Images captured per day/week/month
- Sensor data trends (temperature, humidity)
- Device health metrics
- Error patterns

### 4. Optimize Storage
Implement:
- Automatic thumbnail generation (resize images on upload)
- Image compression (reduce JPEG quality for older images)
- Lifecycle policies (delete images > 90 days old)
- CDN caching for frequently accessed images

## 📞 Support

### Get Help
- Check logs in Render dashboard
- Run verification queries in Supabase
- Review error codes in README.md
- Check `device_errors` table for detailed error info

### Common Questions

**Q: Can I run multiple workers?**
A: Yes! Render can auto-scale. Each worker instance will process different devices.

**Q: What happens if worker crashes during assembly?**
A: On restart, active assemblies are lost. Devices will retry on next wake cycle.

**Q: Can I change MQTT broker?**
A: Yes, update `MQTT_HOST`, `MQTT_PORT`, credentials in Render environment.

**Q: How do I add more device data fields?**
A: Update `sensor_readings` table schema, then modify `insert_sensor_reading()` in `app.py`.

## ✅ Deployment Checklist

Before going to production:

- [ ] Supabase storage bucket `gxp-captures` created (private)
- [ ] RLS migration run successfully
- [ ] Worker tested locally with `test_mqtt.py`
- [ ] Code pushed to GitHub
- [ ] Render worker created and deployed
- [ ] Environment secrets set in Render
- [ ] Worker logs show successful MQTT connection
- [ ] Test device sends image successfully
- [ ] Image appears in Supabase Storage
- [ ] Capture record has `ingest_status='stored'`
- [ ] Sensor data appears in `sensor_readings`
- [ ] No errors in `device_errors` table

---

**You're all set!** 🚀 Your ESP32 fleet can now stream images and sensor data to your Supabase backend in real-time.
