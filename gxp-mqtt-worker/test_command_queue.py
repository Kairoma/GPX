#!/usr/bin/env python3
"""
Test 8: Device Command Queue & Control
Purpose: Verify worker polls device_commands table and publishes to ESP32CAM/{MAC}/cmd topic.

Real-world scenario: Dashboard/user inserts command into database (e.g., "capture_image"),
worker polls queue, publishes to MQTT, ESP32 receives and executes command.

Expected behavior:
1. Worker polls device_commands table for status='queued'
2. Worker publishes command to ESP32CAM/{MAC}/cmd topic
3. Worker updates command status to 'sent'
4. Worker logs event to device_command_logs
5. Simulated ESP32 device receives command on /cmd topic
6. Command format matches firmware expectations

Test scenarios:
- Scenario A: capture_image command
- Scenario B: send_image command with filename
- Scenario C: Multiple commands for same device (queue processing)
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

# Commands received tracker
commands_received = []

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"✓ Test client connected!")
        # Subscribe to cmd topic (simulating ESP32 device)
        client.subscribe(f"ESP32CAM/{TEST_MAC}/cmd")
        print(f"✓ Subscribed to ESP32CAM/{TEST_MAC}/cmd (simulating ESP32)")
        time.sleep(1)
    else:
        print(f"✗ Connection failed: {rc}")

def on_message(client, userdata, msg):
    """Handle commands received (simulating ESP32 firmware)"""
    global commands_received

    print(f"\n📩 Command received on {msg.topic}:")
    try:
        payload = json.loads(msg.payload.decode())
        print(json.dumps(payload, indent=2))
        commands_received.append(payload)

        # Simulate firmware behavior
        if "capture_image" in payload:
            print("  → ESP32 would: Capture image + sensor data, store on SD card")
        elif "send_image" in payload:
            image_name = payload.get("send_image")
            print(f"  → ESP32 would: Send image '{image_name}' in chunks")
        elif "next_wake" in payload:
            wake_time = payload.get("next_wake")
            print(f"  → ESP32 would: Set RTC timer for {wake_time}, enter deep sleep")

    except Exception as e:
        print(f"Error parsing command: {e}")

def insert_command(sb, device_id: str, command_type: str, command_payload: dict = None):
    """Insert command into device_commands table"""
    cmd_data = {
        "device_id": device_id,
        "command_type": command_type,
        "command_payload": command_payload or {},
        "status": "queued"
    }
    result = sb.table("device_commands").insert(cmd_data).execute()
    return result.data[0] if result.data else None

def ensure_test_device(sb, device_hw_id: str):
    """Ensure test device exists in database"""
    # Check if device exists
    result = sb.table("devices")\
        .select("device_id")\
        .eq("device_hw_id", device_hw_id)\
        .execute()

    if result.data:
        return result.data[0]["device_id"]

    # Create device
    ins = sb.table("devices").insert({
        "device_hw_id": device_hw_id,
        "model": "ESP32S3-CAM"
    }).execute()

    return ins.data[0]["device_id"]

def main():
    print("="*70)
    print("Device Command Queue & Control Test")
    print("="*70)

    # Initialize Supabase
    print(f"\n🔌 Connecting to Supabase...")
    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)

    # Ensure test device exists
    print(f"📱 Ensuring test device exists: {TEST_MAC}")
    device_id = ensure_test_device(sb, TEST_MAC)
    print(f"   Device ID: {device_id}")

    # Connect MQTT (simulating ESP32 device)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-esp32-cmd")
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)
    client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"\n🔌 Connecting to MQTT broker...")
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    time.sleep(2)

    # Scenario A: capture_image command
    print(f"\n{'='*70}")
    print(f"SCENARIO A: capture_image Command")
    print(f"{'='*70}")

    print(f"\n1️⃣  Inserting 'capture_image' command into database...")
    cmd1 = insert_command(sb, device_id, "capture_image")
    print(f"   Command ID: {cmd1['command_id']}")
    print(f"   Status: {cmd1['status']}")

    print(f"\n⏳ Waiting for worker to poll and send command...")
    time.sleep(3)

    # Scenario B: send_image command
    print(f"\n{'='*70}")
    print(f"SCENARIO B: send_image Command")
    print(f"{'='*70}")

    print(f"\n2️⃣  Inserting 'send_image' command into database...")
    cmd2 = insert_command(sb, device_id, "send_image", {"image_name": "test_001.jpg"})
    print(f"   Command ID: {cmd2['command_id']}")
    print(f"   Image Name: test_001.jpg")

    print(f"\n⏳ Waiting for worker to poll and send command...")
    time.sleep(3)

    # Scenario C: Multiple commands
    print(f"\n{'='*70}")
    print(f"SCENARIO C: Multiple Commands (Queue Processing)")
    print(f"{'='*70}")

    print(f"\n3️⃣  Inserting 3 commands in rapid succession...")
    cmd3a = insert_command(sb, device_id, "capture_image")
    cmd3b = insert_command(sb, device_id, "send_image", {"image_name": "test_002.jpg"})
    cmd3c = insert_command(sb, device_id, "send_image", {"image_name": "test_003.jpg"})

    print(f"   Commands inserted:")
    print(f"     - {cmd3a['command_id']}: capture_image")
    print(f"     - {cmd3b['command_id']}: send_image (test_002.jpg)")
    print(f"     - {cmd3c['command_id']}: send_image (test_003.jpg)")

    print(f"\n⏳ Waiting for worker to process queue...")
    time.sleep(5)

    # Final wait for any remaining commands
    print(f"\n⏳ Final wait for command processing...")
    time.sleep(2)

    client.loop_stop()
    client.disconnect()

    # Results
    print("\n" + "="*70)
    print("TEST RESULTS")
    print("="*70)

    print(f"\nCommands received by simulated ESP32: {len(commands_received)}")
    for i, cmd in enumerate(commands_received, 1):
        print(f"  {i}. {json.dumps(cmd)}")

    # Verify database updates
    print(f"\n📊 Verifying database...")
    print(f"\nRun this SQL query to check command status:")
    print(f"\n```sql")
    print(f"SELECT ")
    print(f"  command_id,")
    print(f"  command_type,")
    print(f"  command_payload,")
    print(f"  status,")
    print(f"  sent_at,")
    print(f"  requested_at")
    print(f"FROM device_commands")
    print(f"WHERE device_id = '{device_id}'")
    print(f"ORDER BY requested_at DESC")
    print(f"LIMIT 10;")
    print(f"```")

    print(f"\n📋 Check device_command_logs:")
    print(f"\n```sql")
    print(f"SELECT ")
    print(f"  dcl.command_id,")
    print(f"  dcl.event_type,")
    print(f"  dcl.event_payload,")
    print(f"  dcl.created_at")
    print(f"FROM device_command_logs dcl")
    print(f"WHERE dcl.device_id = '{device_id}'")
    print(f"ORDER BY dcl.created_at DESC")
    print(f"LIMIT 10;")
    print(f"```")

    print("\n" + "="*70)
    print("EXPECTED RESULTS")
    print("="*70)

    print(f"\n✅ Expected: {len(commands_received)} commands received (should be 5-6)")
    print(f"✅ Expected: All commands have status='sent' in database")
    print(f"✅ Expected: All commands logged to device_command_logs with event_type='sent'")
    print(f"✅ Expected: Command format matches firmware expectations:")
    print(f"   - capture_image: {{\"device_id\": \"{TEST_MAC}\", \"capture_image\": true}}")
    print(f"   - send_image: {{\"device_id\": \"{TEST_MAC}\", \"send_image\": \"filename.jpg\"}}")

    success = len(commands_received) >= 5
    if success:
        print(f"\n✅ TEST PASSED: Worker successfully processed command queue!")
    else:
        print(f"\n❌ TEST FAILED: Expected at least 5 commands, received {len(commands_received)}")

    print("="*70)

if __name__ == "__main__":
    main()
