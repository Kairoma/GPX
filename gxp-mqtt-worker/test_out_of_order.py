#!/usr/bin/env python3
"""
Test 4: Out-of-Order Chunk Delivery
Purpose: Verify worker correctly assembles images when chunks arrive out of sequence.

Real-world scenario: Network conditions or MQTT broker behavior may cause chunks
to arrive in non-sequential order (e.g., 2, 0, 3, 1 instead of 0, 1, 2, 3).

Expected behavior:
1. Worker should track chunks by ID using bitset
2. Assembly should succeed regardless of arrival order
3. Final image should be identical to in-order delivery
4. ACK_OK should be sent after all chunks received
"""
import json
import base64
import time
import os
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import ssl
import hashlib

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

TEST_MAC = "OUTOFORDER01"
TEST_IMAGE = "scrambled.jpg"

# Create a 12-byte JPEG with distinct chunks (4 chunks @ 3 bytes each)
# This allows us to verify correct reassembly by checking final hash
JPEG_BYTES = bytes([
    0xFF, 0xD8, 0xAA,  # Chunk 0: SOI + data
    0xBB, 0xCC, 0xDD,  # Chunk 1: data
    0xEE, 0x11, 0x22,  # Chunk 2: data
    0x33, 0xFF, 0xD9   # Chunk 3: data + EOI
])
CHUNK_SIZE = 3
TOTAL_CHUNKS = 4

# Calculate expected hash for verification
EXPECTED_SHA256 = hashlib.sha256(JPEG_BYTES).hexdigest()

# Test different scramble patterns
SCRAMBLE_PATTERNS = [
    {
        "name": "Reverse Order",
        "pattern": [3, 2, 1, 0],
        "description": "Chunks sent in complete reverse"
    },
    {
        "name": "Middle-First",
        "pattern": [2, 1, 3, 0],
        "description": "Middle chunks arrive before edges"
    },
    {
        "name": "Random Scatter",
        "pattern": [1, 3, 0, 2],
        "description": "Completely random arrival order"
    },
    {
        "name": "Last-First",
        "pattern": [3, 0, 1, 2],
        "description": "Last chunk arrives first (edge case)"
    }
]

test_results = []
ack_received = False

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"✓ Connected!")
        client.subscribe(f"ESP32CAM/{TEST_MAC}/ack")
        print(f"✓ Subscribed to ESP32CAM/{TEST_MAC}/ack")
        time.sleep(1)
    else:
        print(f"✗ Connection failed: {rc}")

def on_message(client, userdata, msg):
    global ack_received

    print(f"\n📩 Received on {msg.topic}:")
    try:
        payload = json.loads(msg.payload.decode())
        print(json.dumps(payload, indent=2))

        if "ACK_OK" in payload:
            ack_received = True
            print(f"\n✅ ACK_OK received! Image assembly complete.")
        elif "missing_chunks" in payload:
            print(f"\n⚠️  NACK: Missing chunks {payload.get('missing_chunks', [])}")

    except Exception as e:
        print(f"Error: {e}")

def send_scrambled_test(client, pattern_info):
    global ack_received
    ack_received = False

    pattern = pattern_info["pattern"]
    name = pattern_info["name"]
    desc = pattern_info["description"]

    print(f"\n{'='*70}")
    print(f"TEST: {name}")
    print(f"{'='*70}")
    print(f"Description: {desc}")
    print(f"Chunk order: {pattern}")
    print(f"Expected hash: {EXPECTED_SHA256[:16]}...")

    # 1. Status
    print(f"\n📤 Step 1: Sending status...")
    status = {"device_id": TEST_MAC, "status": "Alive", "pendingImg": 1}
    client.publish(f"ESP32CAM/{TEST_MAC}/status", json.dumps(status), qos=1)
    time.sleep(0.5)

    # 2. Metadata
    print(f"\n📤 Step 2: Sending metadata ({TOTAL_CHUNKS} chunks)...")
    metadata = {
        "device_id": TEST_MAC,
        "capture_timeStamp": "2025-10-04T21:30:00Z",
        "image_name": TEST_IMAGE,
        "image_size": len(JPEG_BYTES),
        "max_chunks_size": CHUNK_SIZE,
        "total_chunk_count": TOTAL_CHUNKS,
        "location": "out_of_order_test",
        "error": 0,
        "temperature": 23.5,
        "humidity": 52.0,
        "pressure": 1012.5,
        "gas_resistance": 51000.0
    }
    client.publish(f"ESP32CAM/{TEST_MAC}/data", json.dumps(metadata), qos=1)
    time.sleep(0.5)

    # 3. Send chunks in scrambled order
    print(f"\n📤 Step 3: Sending chunks in scrambled order: {pattern}")

    for chunk_id in pattern:
        start = chunk_id * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, len(JPEG_BYTES))
        chunk_bytes = JPEG_BYTES[start:end]
        chunk_b64 = base64.b64encode(chunk_bytes).decode()

        chunk = {
            "device_id": TEST_MAC,
            "image_name": TEST_IMAGE,
            "chunk_id": chunk_id,
            "max_chunk_size": CHUNK_SIZE,
            "payload": chunk_b64
        }

        print(f"   → Chunk {chunk_id}: {chunk_bytes.hex()}")
        client.publish(f"ESP32CAM/{TEST_MAC}/data", json.dumps(chunk), qos=1)
        time.sleep(0.3)

    print(f"\n⏳ Waiting for assembly and ACK...")

    # Wait for ACK
    timeout = 10
    elapsed = 0
    while elapsed < timeout and not ack_received:
        time.sleep(0.5)
        elapsed += 0.5

    # Record result
    result = {
        "pattern_name": name,
        "pattern": pattern,
        "ack_received": ack_received,
        "status": "✅ PASS" if ack_received else "❌ FAIL"
    }
    test_results.append(result)

    time.sleep(2)  # Gap between tests

def main():
    print("="*70)
    print("Out-of-Order Chunk Delivery Test Suite")
    print("="*70)
    print(f"\nDevice: {TEST_MAC}")
    print(f"Image: {TEST_IMAGE} ({len(JPEG_BYTES)} bytes, {TOTAL_CHUNKS} chunks)")
    print(f"Expected SHA256: {EXPECTED_SHA256}")
    print(f"\nTesting {len(SCRAMBLE_PATTERNS)} different scramble patterns...")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="out-of-order-test")
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"\nConnecting to {MQTT_HOST}:{MQTT_PORT}...")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(2)

    # Run all scramble pattern tests
    for pattern_info in SCRAMBLE_PATTERNS:
        send_scrambled_test(client, pattern_info)

    client.loop_stop()
    client.disconnect()

    # Print final results
    print("\n" + "="*70)
    print("TEST RESULTS SUMMARY")
    print("="*70)

    for result in test_results:
        print(f"{result['status']} {result['pattern_name']}: {result['pattern']}")

    passed = sum(1 for r in test_results if r['ack_received'])
    total = len(test_results)

    print(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("\n✅ ALL TESTS PASSED: Worker correctly handles out-of-order chunks!")
        print("\nVerification Steps:")
        print("1. Check Supabase Storage for image:")
        print(f"   Path: captures/{TEST_MAC}/2025/10/04/{TEST_IMAGE}")
        print(f"2. Verify image SHA256 hash: {EXPECTED_SHA256}")
        print("3. Download and check JPEG is valid (opens correctly)")
        print("\nSQL Verification:")
        print(f"SELECT image_sha256, image_bytes, ingest_status FROM captures")
        print(f"WHERE device_hw_id='{TEST_MAC}' ORDER BY created_at DESC LIMIT 1;")
    else:
        print(f"\n❌ {total - passed} TEST(S) FAILED")
        print("Worker may not be correctly handling out-of-order chunk delivery.")

    print("="*70)

if __name__ == "__main__":
    main()
