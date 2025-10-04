#!/usr/bin/env python3
"""
Quick MQTT test script to verify worker is receiving messages.
Publishes test metadata and chunks to simulate an ESP32 device.
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

TEST_MAC = "AABBCCDDEEFF"
TEST_IMAGE = "test_image_001.jpg"

# Minimal valid JPEG (4 bytes: SOI + EOI)
JPEG_BYTES = bytes([0xFF, 0xD8, 0xFF, 0xD9])

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("✓ Connected to MQTT broker")
        # Subscribe to ACK topic to see worker responses
        client.subscribe(f"ESP32CAM/{TEST_MAC}/ack")
        print(f"✓ Subscribed to ESP32CAM/{TEST_MAC}/ack")
    else:
        print(f"✗ Connection failed with code {rc}")

def on_message(client, userdata, msg):
    print(f"\n📩 Received on {msg.topic}:")
    try:
        payload = json.loads(msg.payload.decode())
        print(json.dumps(payload, indent=2))
    except:
        print(msg.payload.decode())

def main():
    print("=" * 60)
    print("GXP MQTT Worker Test - ESP32 Simulator")
    print("=" * 60)

    # Create client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-esp32-sim")
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect
    print(f"Connecting to {MQTT_HOST}:{MQTT_PORT}...")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(2)

    # 1. Send status message
    print(f"\n📤 Publishing status message...")
    status = {
        "device_id": TEST_MAC,
        "status": "Alive",
        "pendingImg": 0
    }
    client.publish(f"ESP32CAM/{TEST_MAC}/status", json.dumps(status), qos=1)
    print(json.dumps(status, indent=2))
    time.sleep(1)

    # 2. Send metadata
    print(f"\n📤 Publishing image metadata...")
    metadata = {
        "device_id": TEST_MAC,
        "capture_timeStamp": "2025-10-04T18:30:00Z",
        "image_name": TEST_IMAGE,
        "image_size": len(JPEG_BYTES),
        "max_chunks_size": 2,  # 2 bytes per chunk
        "total_chunk_count": 2,
        "location": "test_lab",
        "error": 0,
        "temperature": 22.5,
        "humidity": 50.0,
        "pressure": 1013.25,
        "gas_resistance": 54321.0
    }
    client.publish(f"ESP32CAM/{TEST_MAC}/data", json.dumps(metadata), qos=1)
    print(json.dumps(metadata, indent=2))
    time.sleep(1)

    # 3. Send chunks
    for i in range(2):
        chunk_bytes = JPEG_BYTES[i*2:(i+1)*2]
        chunk_b64 = base64.b64encode(chunk_bytes).decode()

        chunk = {
            "device_id": TEST_MAC,
            "image_name": TEST_IMAGE,
            "chunk_id": i,
            "max_chunk_size": 2,
            "payload": chunk_b64
        }

        print(f"\n📤 Publishing chunk {i}...")
        print(f"   Bytes: {chunk_bytes.hex()}")
        print(f"   Base64: {chunk_b64}")

        client.publish(f"ESP32CAM/{TEST_MAC}/data", json.dumps(chunk), qos=1)
        time.sleep(0.5)

    print("\n" + "=" * 60)
    print("✓ All test messages sent!")
    print("Waiting for ACK from worker...")
    print("(Press Ctrl+C to exit)")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
