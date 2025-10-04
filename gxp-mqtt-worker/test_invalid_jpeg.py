#!/usr/bin/env python3
"""
Test invalid JPEG detection.
Tests multiple scenarios:
1. Missing SOI marker (0xFF 0xD8)
2. Missing EOI marker (0xFF 0xD9)
3. Wrong file signature entirely
4. Size mismatch (declared vs actual)

Expected behavior:
- Worker should detect invalid JPEG
- Should log error in device_errors table
- Should mark capture as "failed"
- Should NOT upload to storage
"""
import json
import base64
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

TEST_CASES = [
    {
        "name": "Missing SOI",
        "device_id": "INVALID101",
        "image_name": "missing_soi.jpg",
        "data": bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xFF, 0xD9]),  # No SOI, has EOI
        "expected_error": "Invalid JPEG: missing SOI or EOI markers"
    },
    {
        "name": "Missing EOI",
        "device_id": "INVALID102",
        "image_name": "missing_eoi.jpg",
        "data": bytes([0xFF, 0xD8, 0xAA, 0xBB, 0xCC, 0xDD]),  # Has SOI, no EOI
        "expected_error": "Invalid JPEG: missing SOI or EOI markers"
    },
    {
        "name": "Not a JPEG",
        "device_id": "INVALID103",
        "image_name": "not_jpeg.jpg",
        "data": bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A]),  # PNG signature
        "expected_error": "Invalid JPEG: missing SOI or EOI markers"
    },
    {
        "name": "Size Mismatch",
        "device_id": "INVALID104",
        "image_name": "size_mismatch.jpg",
        "data": bytes([0xFF, 0xD8, 0xAA, 0xBB, 0xFF, 0xD9]),  # 6 bytes
        "declared_size": 100,  # Declare 100 but send 6
        "expected_error": "Size mismatch: declared 100, actual 6"
    }
]

CHUNK_SIZE = 2

test_results = []

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"✓ Connected!")
        # Subscribe to all ACK topics
        for test in TEST_CASES:
            client.subscribe(f"ESP32CAM/{test['device_id']}/ack")
        time.sleep(1)
        run_all_tests(client)
    else:
        print(f"✗ Connection failed: {rc}")

def on_message(client, userdata, msg):
    print(f"\n📩 Received on {msg.topic}:")
    try:
        payload = json.loads(msg.payload.decode())
        print(json.dumps(payload, indent=2))
    except:
        print(msg.payload.decode())

def send_invalid_image(client, test_case):
    print(f"\n{'='*60}")
    print(f"TEST: {test_case['name']}")
    print(f"{'='*60}")

    device_id = test_case['device_id']
    image_name = test_case['image_name']
    jpeg_bytes = test_case['data']
    declared_size = test_case.get('declared_size', len(jpeg_bytes))

    total_chunks = (len(jpeg_bytes) + CHUNK_SIZE - 1) // CHUNK_SIZE

    # 1. Status
    print(f"\n📤 Sending status for {device_id}...")
    status = {"device_id": device_id, "status": "Alive", "pendingImg": 1}
    client.publish(f"ESP32CAM/{device_id}/status", json.dumps(status), qos=1)
    time.sleep(0.3)

    # 2. Metadata
    print(f"📤 Sending metadata...")
    print(f"   Declared size: {declared_size} bytes")
    print(f"   Actual size: {len(jpeg_bytes)} bytes")
    print(f"   Data: {jpeg_bytes.hex()}")

    metadata = {
        "device_id": device_id,
        "capture_timeStamp": "2025-10-04T21:00:00Z",
        "image_name": image_name,
        "image_size": declared_size,
        "max_chunks_size": CHUNK_SIZE,
        "total_chunk_count": total_chunks,
        "location": "invalid_test",
        "error": 0,
        "temperature": 22.0,
        "humidity": 50.0,
        "pressure": 1013.0,
        "gas_resistance": 50000.0
    }
    client.publish(f"ESP32CAM/{device_id}/data", json.dumps(metadata), qos=1)
    time.sleep(0.3)

    # 3. Send chunks
    print(f"📤 Sending {total_chunks} chunks...")
    for chunk_id in range(total_chunks):
        start = chunk_id * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, len(jpeg_bytes))
        chunk_bytes = jpeg_bytes[start:end]
        chunk_b64 = base64.b64encode(chunk_bytes).decode()

        chunk = {
            "device_id": device_id,
            "image_name": image_name,
            "chunk_id": chunk_id,
            "max_chunk_size": CHUNK_SIZE,
            "payload": chunk_b64
        }

        print(f"   Chunk {chunk_id}: {chunk_bytes.hex()}")
        client.publish(f"ESP32CAM/{device_id}/data", json.dumps(chunk), qos=1)
        time.sleep(0.2)

    print(f"\n⏳ Waiting for worker to detect error...")
    time.sleep(2)

def run_all_tests(client):
    print("\n" + "="*60)
    print("Invalid JPEG Detection Test Suite")
    print("="*60)

    for test in TEST_CASES:
        send_invalid_image(client, test)
        time.sleep(3)  # Wait between tests

def main():
    print("="*60)
    print("Invalid JPEG Detection Test")
    print("="*60)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="invalid-jpeg-test")
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"\nConnecting to {MQTT_HOST}:{MQTT_PORT}...")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    # Run for 30 seconds
    time.sleep(30)

    client.loop_stop()
    client.disconnect()

    # Print verification instructions
    print("\n" + "="*60)
    print("VERIFICATION")
    print("="*60)
    print("\nCheck Supabase for errors:")
    print("\n```sql")
    print("-- Should show 4 error records with severity='error'")
    print("SELECT de.error_code, de.severity, de.message, d.device_hw_id")
    print("FROM device_errors de")
    print("JOIN devices d ON de.device_id = d.device_id")
    print("WHERE d.device_hw_id LIKE 'INVALID1%'")
    print("ORDER BY de.occurred_at DESC;")
    print("")
    print("-- ALL 4 captures should be 'failed' (not 'stored')")
    print("SELECT c.device_capture_id, c.ingest_status, c.ingest_error, d.device_hw_id")
    print("FROM captures c")
    print("JOIN devices d ON c.device_id = d.device_id")
    print("WHERE d.device_hw_id LIKE 'INVALID1%'")
    print("ORDER BY c.created_at DESC;")
    print("```")
    print("\n" + "="*60)
    print("\nExpected Errors:")
    for test in TEST_CASES:
        print(f"  • {test['device_id']}: {test['expected_error']}")
    print("="*60)

if __name__ == "__main__":
    main()
