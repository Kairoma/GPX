#!/usr/bin/env python3
"""
Test 8: Device Command Queue & Control (Simplified for Render execution)
Run via: timeout 30 python3 test_command_queue_simple.py
"""
import json
import time
import os
from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import ssl
from supabase import create_client

load_dotenv()

MQTT_HOST = os.getenv("MQTT_HOST", "1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE")

TEST_MAC = "CMDTEST01"
commands_received = []

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"✓ Connected! Subscribing to ESP32CAM/{TEST_MAC}/cmd")
        client.subscribe(f"ESP32CAM/{TEST_MAC}/cmd")
        time.sleep(1)
    else:
        print(f"✗ Connection failed: {rc}")

def on_message(client, userdata, msg):
    global commands_received
    print(f"\n📩 Command received: {msg.topic}")
    try:
        payload = json.loads(msg.payload.decode())
        print(f"   {json.dumps(payload)}")
        commands_received.append(payload)
    except Exception as e:
        print(f"Error: {e}")

def insert_command(sb, device_id: str, command_type: str, command_payload: dict = None):
    cmd_data = {
        "device_id": device_id,
        "command_type": command_type,
        "command_payload": command_payload or {},
        "status": "queued"
    }
    result = sb.table("device_commands").insert(cmd_data).execute()
    return result.data[0] if result.data else None

def ensure_test_device(sb, device_hw_id: str):
    result = sb.table("devices").select("device_id").eq("device_hw_id", device_hw_id).execute()
    if result.data:
        return result.data[0]["device_id"]

    ins = sb.table("devices").insert({
        "device_hw_id": device_hw_id,
        "model": "ESP32S3-CAM"
    }).execute()
    return ins.data[0]["device_id"]

def main():
    print("="*60)
    print("Test #8: Command Queue & Control")
    print("="*60)

    # Initialize Supabase
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
        print("❌ Missing Supabase credentials in environment")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
    device_id = ensure_test_device(sb, TEST_MAC)
    print(f"✓ Device ID: {device_id}")

    # Connect MQTT
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-esp32-cmd")
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    time.sleep(2)

    # Insert test commands
    print("\n1️⃣  Inserting capture_image command...")
    cmd1 = insert_command(sb, device_id, "capture_image")
    print(f"   Command ID: {cmd1['command_id']}")
    time.sleep(3)

    print("\n2️⃣  Inserting send_image command...")
    cmd2 = insert_command(sb, device_id, "send_image", {"image_name": "test_001.jpg"})
    print(f"   Command ID: {cmd2['command_id']}")
    time.sleep(3)

    print("\n3️⃣  Inserting 3 commands rapidly...")
    insert_command(sb, device_id, "capture_image")
    insert_command(sb, device_id, "send_image", {"image_name": "test_002.jpg"})
    insert_command(sb, device_id, "send_image", {"image_name": "test_003.jpg"})
    time.sleep(5)

    client.loop_stop()
    client.disconnect()

    # Results
    print("\n" + "="*60)
    print(f"Commands received: {len(commands_received)}")
    for i, cmd in enumerate(commands_received, 1):
        print(f"  {i}. {json.dumps(cmd)}")

    success = len(commands_received) >= 5
    if success:
        print(f"\n✅ TEST PASSED: {len(commands_received)} commands received!")
    else:
        print(f"\n❌ TEST FAILED: Expected 5+, got {len(commands_received)}")
    print("="*60)

if __name__ == "__main__":
    main()
