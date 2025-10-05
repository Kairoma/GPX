#!/usr/bin/env python3
"""
Test 6: Duplicate Chunk Handling
Purpose: Verify worker correctly handles duplicate chunks (same chunk_id sent multiple times).

Real-world scenario: Network issues or ESP32 firmware bugs may cause the same
chunk to be retransmitted. Worker should:
1. Accept the first instance of a chunk
2. Ignore subsequent duplicates (idempotent behavior)
3. Not corrupt the assembly with duplicate data
4. Successfully complete assembly with correct final image

Expected behavior:
- Worker tracks chunks by ID using bitset
- Duplicate chunks are silently ignored (not an error)
- Final image is correct (SHA256 verification)
- ACK_OK sent after all unique chunks received
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

TEST_MAC = "DUPLICATE01"
TEST_IMAGE = "duplicate_test.jpg"

# 10-byte JPEG: SOI + data + EOI (5 chunks @ 2 bytes each)
JPEG_BYTES = bytes([0xFF, 0xD8, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0xFF, 0xD9])
CHUNK_SIZE = 2
TOTAL_CHUNKS = 5

EXPECTED_SHA256 = hashlib.sha256(JPEG_BYTES).hexdigest()

ack_received = False
nack_count = 0

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"✓ Connected!")
        client.subscribe(f"ESP32CAM/{TEST_MAC}/ack")
        print(f"✓ Subscribed to ESP32CAM/{TEST_MAC}/ack")
        time.sleep(1)
    else:
        print(f"✗ Connection failed: {rc}")

def on_message(client, userdata, msg):
    global ack_received, nack_count

    print(f"\n📩 Received on {msg.topic}:")
    try:
        payload = json.loads(msg.payload.decode())
        print(json.dumps(payload, indent=2))

        if "ACK_OK" in payload:
            ack_received = True
            print(f"\n✅ ACK_OK received! Assembly complete.")
        elif "missing_chunks" in payload:
            nack_count += 1
            missing = payload.get("missing_chunks", [])
            print(f"\n⚠️  NACK #{nack_count}: {len(missing)} missing chunks")

    except Exception as e:
        print(f"Error: {e}")

def send_chunk(client, chunk_id, chunk_bytes):
    """Send a single chunk"""
    chunk_b64 = base64.b64encode(chunk_bytes).decode()
    chunk = {
        "device_id": TEST_MAC,
        "image_name": TEST_IMAGE,
        "chunk_id": chunk_id,
        "max_chunk_size": CHUNK_SIZE,
        "payload": chunk_b64
    }
    client.publish(f"ESP32CAM/{TEST_MAC}/data", json.dumps(chunk), qos=1)

def main():
    global ack_received, nack_count

    print("="*70)
    print("Duplicate Chunk Handling Test")
    print("="*70)
    print(f"\nDevice: {TEST_MAC}")
    print(f"Image: {TEST_IMAGE} ({len(JPEG_BYTES)} bytes, {TOTAL_CHUNKS} chunks)")
    print(f"Expected SHA256: {EXPECTED_SHA256}")
    print("\nTest pattern: Send chunks with intentional duplicates")
    print("  - Chunk 0: sent once")
    print("  - Chunk 1: sent TWICE (duplicate)")
    print("  - Chunk 2: sent THREE times (2 duplicates)")
    print("  - Chunk 3: sent once")
    print("  - Chunk 4: sent TWICE (duplicate)")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="duplicate-test")
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"\nConnecting to {MQTT_HOST}:{MQTT_PORT}...")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(2)

    # 1. Status
    print(f"\n📤 Step 1: Sending status...")
    status = {"device_id": TEST_MAC, "status": "Alive", "pendingImg": 1}
    client.publish(f"ESP32CAM/{TEST_MAC}/status", json.dumps(status), qos=1)
    time.sleep(0.5)

    # 2. Metadata
    print(f"\n📤 Step 2: Sending metadata ({TOTAL_CHUNKS} unique chunks)...")
    metadata = {
        "device_id": TEST_MAC,
        "capture_timeStamp": "2025-10-04T22:00:00Z",
        "image_name": TEST_IMAGE,
        "image_size": len(JPEG_BYTES),
        "max_chunks_size": CHUNK_SIZE,
        "total_chunk_count": TOTAL_CHUNKS,
        "location": "duplicate_test",
        "error": 0,
        "temperature": 23.0,
        "humidity": 53.0,
        "pressure": 1012.0,
        "gas_resistance": 49000.0
    }
    client.publish(f"ESP32CAM/{TEST_MAC}/data", json.dumps(metadata), qos=1)
    time.sleep(0.5)

    # 3. Send chunks with duplicates
    print(f"\n📤 Step 3: Sending chunks with duplicates...")

    # Chunk 0 (sent once)
    chunk_id = 0
    chunk_bytes = JPEG_BYTES[chunk_id*CHUNK_SIZE:(chunk_id+1)*CHUNK_SIZE]
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (sent 1x)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)

    # Chunk 1 (sent TWICE - duplicate)
    chunk_id = 1
    chunk_bytes = JPEG_BYTES[chunk_id*CHUNK_SIZE:(chunk_id+1)*CHUNK_SIZE]
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (sent 1x)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (DUPLICATE)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)

    # Chunk 2 (sent THREE times - 2 duplicates)
    chunk_id = 2
    chunk_bytes = JPEG_BYTES[chunk_id*CHUNK_SIZE:(chunk_id+1)*CHUNK_SIZE]
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (sent 1x)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (DUPLICATE #1)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (DUPLICATE #2)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)

    # Chunk 3 (sent once)
    chunk_id = 3
    chunk_bytes = JPEG_BYTES[chunk_id*CHUNK_SIZE:(chunk_id+1)*CHUNK_SIZE]
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (sent 1x)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)

    # Chunk 4 (sent TWICE - duplicate)
    chunk_id = 4
    chunk_bytes = JPEG_BYTES[chunk_id*CHUNK_SIZE:(chunk_id+1)*CHUNK_SIZE]
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (sent 1x)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)
    print(f"   Chunk {chunk_id}: {chunk_bytes.hex()} (DUPLICATE)")
    send_chunk(client, chunk_id, chunk_bytes)
    time.sleep(0.3)

    print(f"\n✓ All chunks sent (5 unique + 4 duplicates = 9 total messages)")
    print(f"⏳ Waiting for assembly and ACK...")

    # Wait for ACK
    timeout = 15
    elapsed = 0
    while elapsed < timeout and not ack_received:
        time.sleep(0.5)
        elapsed += 0.5

    client.loop_stop()
    client.disconnect()

    # Results
    print("\n" + "="*70)
    print("TEST RESULTS")
    print("="*70)

    print(f"ACK_OK received: {'✅ YES' if ack_received else '❌ NO'}")
    print(f"NACK count: {nack_count}")

    if ack_received:
        print("\n✅ TEST PASSED: Worker handled duplicate chunks correctly!")
        print("\nVerification Steps:")
        print("1. Check Supabase Storage for image:")
        print(f"   Path: captures/{TEST_MAC}/2025/10/04/{TEST_IMAGE}")
        print(f"2. Verify image SHA256 hash: {EXPECTED_SHA256}")
        print("\nSQL Verification:")
        print(f"SELECT image_sha256, image_bytes, ingest_status FROM captures")
        print(f"WHERE device_hw_id='{TEST_MAC}' ORDER BY created_at DESC LIMIT 1;")
        print(f"\nExpected SHA256: {EXPECTED_SHA256}")
        print("If SHA256 matches, duplicates were correctly ignored (idempotent).")
    else:
        print("\n❌ TEST FAILED: No ACK received")
        print("Worker may not be correctly handling duplicate chunks.")

    print("="*70)

if __name__ == "__main__":
    main()
