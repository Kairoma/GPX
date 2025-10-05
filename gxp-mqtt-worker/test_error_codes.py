#!/usr/bin/env python3
"""
Test 7: ESP32 Error Code Handling
Purpose: Verify worker correctly processes and logs ESP32-reported capture errors.

Real-world scenario: ESP32 devices report hardware/firmware failures via the 'error'
field in metadata. Common scenarios:
- Camera initialization failure
- Image capture failure
- Sensor read failure
- Memory allocation failure

Expected behavior:
1. Worker logs error to device_errors table with appropriate severity
2. Capture is marked with ingest_status='failed' and descriptive ingest_error
3. Worker still processes and stores sensor data (temp, humidity, etc.)
4. No image upload attempted (no Storage write for failed captures)
5. Worker sends ACK_ERROR or similar acknowledgment to device
"""
import json
import time
import os
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import ssl

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

# Test cases for different ESP32 error codes
ERROR_TEST_CASES = [
    {
        "name": "Camera Init Failure",
        "device_id": "ERROR101",
        "error_code": 1,
        "image_name": "cam_init_fail.jpg",
        "expected_error_msg": "Camera initialization failed",
        "description": "ESP32 reports camera hardware initialization failure"
    },
    {
        "name": "Image Capture Failure",
        "device_id": "ERROR102",
        "error_code": 2,
        "image_name": "capture_fail.jpg",
        "expected_error_msg": "Image capture failed",
        "description": "ESP32 failed to capture image from camera"
    },
    {
        "name": "Sensor Read Failure",
        "device_id": "ERROR103",
        "error_code": 3,
        "image_name": "sensor_fail.jpg",
        "expected_error_msg": "Sensor read failed",
        "description": "ESP32 failed to read BME680 sensor data"
    },
    {
        "name": "Memory Allocation Failure",
        "device_id": "ERROR104",
        "error_code": 4,
        "image_name": "memory_fail.jpg",
        "expected_error_msg": "Memory allocation failed",
        "description": "ESP32 ran out of memory during capture"
    },
    {
        "name": "Unknown Error Code",
        "device_id": "ERROR105",
        "error_code": 99,
        "image_name": "unknown_error.jpg",
        "expected_error_msg": "Unknown error",
        "description": "ESP32 reports unrecognized error code"
    }
]

test_results = []
ack_received = {}

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"✓ Connected!")
        # Subscribe to all ACK topics
        for test in ERROR_TEST_CASES:
            client.subscribe(f"ESP32CAM/{test['device_id']}/ack")
        time.sleep(1)
    else:
        print(f"✗ Connection failed: {rc}")

def on_message(client, userdata, msg):
    print(f"\n📩 Received on {msg.topic}:")
    try:
        payload = json.loads(msg.payload.decode())
        print(json.dumps(payload, indent=2))

        # Track ACK responses
        for test in ERROR_TEST_CASES:
            if test['device_id'] in msg.topic:
                ack_received[test['device_id']] = payload
                break

    except Exception as e:
        print(f"Error parsing message: {e}")

def send_error_test(client, test_case):
    """Send metadata with error code, no image chunks"""
    print(f"\n{'='*70}")
    print(f"TEST: {test_case['name']}")
    print(f"{'='*70}")
    print(f"Description: {test_case['description']}")
    print(f"Error Code: {test_case['error_code']}")

    device_id = test_case['device_id']

    # 1. Status
    print(f"\n📤 Step 1: Sending status...")
    status = {"device_id": device_id, "status": "Alive", "pendingImg": 1}
    client.publish(f"ESP32CAM/{device_id}/status", json.dumps(status), qos=1)
    time.sleep(0.5)

    # 2. Metadata with error code (and valid sensor data)
    print(f"\n📤 Step 2: Sending metadata with ERROR CODE {test_case['error_code']}...")
    metadata = {
        "device_id": device_id,
        "capture_timeStamp": "2025-10-05T17:30:00Z",
        "image_name": test_case['image_name'],
        "image_size": 0,  # No image when error occurs
        "max_chunks_size": 1024,
        "total_chunk_count": 0,  # No chunks will be sent
        "location": "error_test_lab",
        "error": test_case['error_code'],  # ← ESP32 error code
        "temperature": 23.5,  # Sensor data may still be valid
        "humidity": 55.0,
        "pressure": 1012.0,
        "gas_resistance": 52000.0
    }
    client.publish(f"ESP32CAM/{device_id}/data", json.dumps(metadata), qos=1)
    print(json.dumps(metadata, indent=2))
    time.sleep(1.5)

    # 3. NO chunks sent (error case - no image captured)
    print(f"📤 Step 3: No chunks sent (error={test_case['error_code']} - no image)")

    print(f"\n⏳ Waiting for worker to process error...")
    time.sleep(2)

def main():
    print("="*70)
    print("ESP32 Error Code Handling Test Suite")
    print("="*70)
    print(f"\nTesting {len(ERROR_TEST_CASES)} different ESP32 error scenarios...")
    print(f"\nKey Validation Points:")
    print(f"  1. Worker logs ESP32 errors to device_errors table")
    print(f"  2. Capture marked 'failed' with descriptive ingest_error")
    print(f"  3. Sensor data still stored (temperature, humidity, etc.)")
    print(f"  4. No Storage upload attempted (no image to upload)")
    print(f"  5. Worker sends appropriate ACK response")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="error-code-test")
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"\nConnecting to {MQTT_HOST}:{MQTT_PORT}...")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(2)

    # Run all error code tests
    for test_case in ERROR_TEST_CASES:
        send_error_test(client, test_case)
        time.sleep(3)  # Gap between tests

    print(f"\n⏳ Waiting for final worker processing...")
    time.sleep(3)

    client.loop_stop()
    client.disconnect()

    # Print results
    print("\n" + "="*70)
    print("TEST EXECUTION COMPLETE")
    print("="*70)

    print(f"\nACK Responses Received:")
    for device_id, ack in ack_received.items():
        print(f"  {device_id}: {ack}")

    if not ack_received:
        print(f"  (No ACK responses received - worker may handle errors silently)")

    # Verification instructions
    print("\n" + "="*70)
    print("DATABASE VERIFICATION REQUIRED")
    print("="*70)

    print("\n1. Check device_errors table for ESP32 error logging:")
    print("\n```sql")
    print("SELECT ")
    print("  d.device_hw_id,")
    print("  de.error_code,")
    print("  de.severity,")
    print("  de.message,")
    print("  de.occurred_at")
    print("FROM device_errors de")
    print("JOIN devices d ON de.device_id = d.device_id")
    print("WHERE d.device_hw_id LIKE 'ERROR1%'")
    print("ORDER BY de.occurred_at DESC;")
    print("```")

    print("\n2. Verify captures table for failed status:")
    print("\n```sql")
    print("SELECT ")
    print("  d.device_hw_id,")
    print("  c.device_capture_id,")
    print("  c.ingest_status,")
    print("  c.ingest_error,")
    print("  c.image_bytes,")
    print("  c.temperature,")
    print("  c.humidity")
    print("FROM captures c")
    print("JOIN devices d ON c.device_id = d.device_id")
    print("WHERE d.device_hw_id LIKE 'ERROR1%'")
    print("ORDER BY c.created_at DESC;")
    print("```")

    print("\n3. Verify Supabase Storage:")
    print("   → Check that NO images uploaded for error cases")
    print("   → Path: captures/ERROR10*/2025/10/05/*.jpg should be EMPTY")

    print("\n" + "="*70)
    print("EXPECTED RESULTS")
    print("="*70)

    for test in ERROR_TEST_CASES:
        print(f"\n{test['device_id']} ({test['name']}):")
        print(f"  ✓ device_errors: error_code={test['error_code']}, severity='error'")
        print(f"  ✓ captures: ingest_status='failed', sensor data stored")
        print(f"  ✓ Storage: No image uploaded")

    print("\n" + "="*70)
    print("\n⚠️  MANUAL VERIFICATION REQUIRED")
    print("Run the SQL queries above and confirm:")
    print("  1. All 5 errors logged to device_errors table")
    print("  2. All 5 captures marked 'failed' with ingest_error set")
    print("  3. Sensor data (temp/humidity/etc.) still stored in captures")
    print("  4. No images in Supabase Storage for these devices")
    print("="*70)

if __name__ == "__main__":
    main()
