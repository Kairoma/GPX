#!/usr/bin/env python3
"""
Test 5: Concurrent Device Load
Purpose: Verify worker correctly handles multiple devices transmitting simultaneously.

Real-world scenario: Multiple ESP32-CAM devices wake up at similar times and
transmit images concurrently. Worker must maintain separate assembly states
and not mix chunks between devices.

Expected behavior:
1. Worker maintains isolated assembly state per device
2. Each device's image assembles correctly (no cross-contamination)
3. All devices receive their respective ACK_OK
4. SHA256 hashes verify correct per-device assembly
5. No race conditions or memory corruption
"""
import json
import base64
import time
import os
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import ssl
import hashlib
import threading
from datetime import datetime

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

# Define 3 concurrent devices with unique data
DEVICES = [
    {
        "device_id": "CONCURRENT01",
        "image_name": "device1.jpg",
        # Unique pattern: starts with 0xFF 0xD8 (SOI), ends with 0xFF 0xD9 (EOI)
        "data": bytes([0xFF, 0xD8, 0x11, 0x11, 0x11, 0x11, 0xFF, 0xD9]),
        "chunk_size": 2,
        "color": "\033[94m"  # Blue
    },
    {
        "device_id": "CONCURRENT02",
        "image_name": "device2.jpg",
        # Different pattern
        "data": bytes([0xFF, 0xD8, 0x22, 0x22, 0x22, 0x22, 0xFF, 0xD9]),
        "chunk_size": 2,
        "color": "\033[92m"  # Green
    },
    {
        "device_id": "CONCURRENT03",
        "image_name": "device3.jpg",
        # Different pattern
        "data": bytes([0xFF, 0xD8, 0x33, 0x33, 0x33, 0x33, 0xFF, 0xD9]),
        "chunk_size": 2,
        "color": "\033[93m"  # Yellow
    }
]

RESET = "\033[0m"

# Calculate expected hashes
for device in DEVICES:
    device["expected_hash"] = hashlib.sha256(device["data"]).hexdigest()
    device["total_chunks"] = len(device["data"]) // device["chunk_size"]
    device["ack_received"] = False
    device["start_time"] = None
    device["end_time"] = None

results_lock = threading.Lock()

def on_message(client, userdata, msg):
    """Handle ACK messages from worker"""
    # Find which device this ACK is for
    for device in DEVICES:
        if device["device_id"] in msg.topic:
            try:
                payload = json.loads(msg.payload.decode())

                if "ACK_OK" in payload:
                    with results_lock:
                        device["ack_received"] = True
                        device["end_time"] = time.time()
                        elapsed = device["end_time"] - device["start_time"]

                    print(f"{device['color']}✅ [{device['device_id']}] ACK_OK received ({elapsed:.2f}s){RESET}")

                elif "missing_chunks" in payload:
                    missing = payload.get("missing_chunks", [])
                    print(f"{device['color']}⚠️  [{device['device_id']}] NACK: {len(missing)} missing chunks{RESET}")

            except Exception as e:
                print(f"Error parsing ACK for {device['device_id']}: {e}")
            break

def send_device_data(device):
    """Send complete image sequence for one device"""
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"test-{device['device_id']}"
    )
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()

        # Subscribe to this device's ACK topic
        ack_topic = f"ESP32CAM/{device['device_id']}/ack"
        client.subscribe(ack_topic)

        time.sleep(0.5)  # Brief connection stabilization

        device["start_time"] = time.time()

        # 1. Send status
        print(f"{device['color']}📤 [{device['device_id']}] Sending status{RESET}")
        status = {
            "device_id": device["device_id"],
            "status": "Alive",
            "pendingImg": 1
        }
        client.publish(f"ESP32CAM/{device['device_id']}/status", json.dumps(status), qos=1)
        time.sleep(0.2)

        # 2. Send metadata
        print(f"{device['color']}📤 [{device['device_id']}] Sending metadata ({device['total_chunks']} chunks){RESET}")
        metadata = {
            "device_id": device["device_id"],
            "capture_timeStamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "image_name": device["image_name"],
            "image_size": len(device["data"]),
            "max_chunks_size": device["chunk_size"],
            "total_chunk_count": device["total_chunks"],
            "location": "concurrent_test",
            "error": 0,
            "temperature": 24.0,
            "humidity": 55.0,
            "pressure": 1013.0,
            "gas_resistance": 50000.0
        }
        client.publish(f"ESP32CAM/{device['device_id']}/data", json.dumps(metadata), qos=1)
        time.sleep(0.2)

        # 3. Send chunks
        print(f"{device['color']}📤 [{device['device_id']}] Sending {device['total_chunks']} chunks{RESET}")
        for chunk_id in range(device["total_chunks"]):
            start = chunk_id * device["chunk_size"]
            end = min(start + device["chunk_size"], len(device["data"]))
            chunk_bytes = device["data"][start:end]
            chunk_b64 = base64.b64encode(chunk_bytes).decode()

            chunk = {
                "device_id": device["device_id"],
                "image_name": device["image_name"],
                "chunk_id": chunk_id,
                "max_chunk_size": device["chunk_size"],
                "payload": chunk_b64
            }

            client.publish(f"ESP32CAM/{device['device_id']}/data", json.dumps(chunk), qos=1)
            time.sleep(0.1)  # Small delay between chunks

        print(f"{device['color']}✓ [{device['device_id']}] All chunks sent{RESET}")

        # Wait for ACK
        timeout = 15
        elapsed = 0
        while elapsed < timeout and not device["ack_received"]:
            time.sleep(0.5)
            elapsed += 0.5

        client.loop_stop()
        client.disconnect()

    except Exception as e:
        print(f"{device['color']}✗ [{device['device_id']}] Error: {e}{RESET}")

def main():
    print("="*80)
    print("Concurrent Device Load Test")
    print("="*80)
    print(f"\nTesting {len(DEVICES)} devices transmitting simultaneously...")
    print(f"Each device has unique data pattern for cross-contamination detection\n")

    for device in DEVICES:
        print(f"{device['color']}Device: {device['device_id']}{RESET}")
        print(f"  Image: {device['image_name']}")
        print(f"  Size: {len(device['data'])} bytes ({device['total_chunks']} chunks)")
        print(f"  Expected SHA256: {device['expected_hash'][:16]}...")
        print(f"  Data pattern: {device['data'].hex()}\n")

    print("="*80)
    print("Starting concurrent transmission...\n")

    # Launch all devices in parallel threads
    threads = []
    start_time = time.time()

    for device in DEVICES:
        thread = threading.Thread(target=send_device_data, args=(device,))
        thread.start()
        threads.append(thread)
        time.sleep(0.2)  # Slight stagger to simulate real-world timing

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    total_time = time.time() - start_time

    # Print results
    print("\n" + "="*80)
    print("TEST RESULTS")
    print("="*80)

    all_passed = True
    for device in DEVICES:
        status = "✅ PASS" if device["ack_received"] else "❌ FAIL"
        elapsed = device["end_time"] - device["start_time"] if device["end_time"] else 0

        print(f"{status} {device['device_id']}: ACK in {elapsed:.2f}s" if device["ack_received"]
              else f"{status} {device['device_id']}: No ACK received")

        if not device["ack_received"]:
            all_passed = False

    print(f"\nTotal test duration: {total_time:.2f}s")
    print(f"Overall: {sum(1 for d in DEVICES if d['ack_received'])}/{len(DEVICES)} devices successful")

    if all_passed:
        print("\n✅ ALL DEVICES PASSED: Worker handled concurrent load correctly!")
        print("\nVerification Steps (run these SQL queries):")
        print("\n```sql")
        print("-- Verify all 3 devices were processed")
        print("SELECT d.device_hw_id, c.device_capture_id, c.image_sha256,")
        print("       c.image_bytes, c.ingest_status, c.created_at")
        print("FROM captures c")
        print("JOIN devices d ON c.device_id = d.device_id")
        print("WHERE d.device_hw_id LIKE 'CONCURRENT%'")
        print("ORDER BY c.created_at DESC;")
        print("")
        print("-- Expected SHA256 hashes:")
        for device in DEVICES:
            print(f"-- {device['device_id']}: {device['expected_hash']}")
        print("```")

        print("\n⚠️  CRITICAL VERIFICATION:")
        print("Each device MUST have its own unique SHA256 hash.")
        print("If any hashes match, there was cross-contamination (data mixed between devices)!")

    else:
        print("\n❌ TEST FAILED: Some devices did not receive ACK")
        print("Check Render logs for errors or timeout issues.")

    print("="*80)

if __name__ == "__main__":
    main()
