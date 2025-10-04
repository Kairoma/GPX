#!/usr/bin/env python3
"""
GXP MQTT Worker - ESP32S3-CAM Fleet Ingestion Middleware
Listens to MQTT topics from ESP32S3-CAM devices, assembles chunked images,
stores to Supabase Storage, and persists metadata + sensor data to database.
"""

import os
import ssl
import json
import time
import base64
import hashlib
import logging
import signal
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

import paho.mqtt.client as mqtt
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file (for local development)
load_dotenv()

# ------------ Environment Configuration ------------
MQTT_HOST = os.getenv("MQTT_HOST", "1305ceddedc94b9fa7fba9428fe4624e.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_TLS = os.getenv("MQTT_TLS", "true").lower() == "true"
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "BrainlyTesting")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")

# ESP32 firmware uses these topic patterns:
# ESP32CAM/{MAC}/data   - image chunks + metadata + sensor data
# ESP32CAM/{MAC}/status - device status (alive, pending count)
# ESP32CAM/{MAC}/cmd    - commands from server to device
# ESP32CAM/{MAC}/ack    - acknowledgments from server to device
TOPIC_PATTERN_DATA = os.getenv("TOPIC_PATTERN_DATA", "ESP32CAM/+/data")
TOPIC_PATTERN_STATUS = os.getenv("TOPIC_PATTERN_STATUS", "ESP32CAM/+/status")
TOPIC_PATTERN_ACK = os.getenv("TOPIC_PATTERN_ACK", "ESP32CAM/+/ack")

# Assembly & retry configuration
CAPTURE_TIMEOUT_MS = int(os.getenv("CAPTURE_TIMEOUT_MS", "60000"))
RETRANSMIT_DELAY_MS = int(os.getenv("RETRANSMIT_DELAY_MS", "3000"))
RETRANSMIT_MAX = int(os.getenv("RETRANSMIT_MAX", "3"))

# Supabase configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE = os.getenv("SUPABASE_SERVICE_ROLE")
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "gxp-captures")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("gxp-worker")

# ------------ Supabase Client ------------
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE:
    log.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE must be set!")
    exit(1)

sb: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
log.info("Supabase client initialized: %s", SUPABASE_URL)


# ------------ Helper Functions ------------
def now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def sha256_hex(b: bytes) -> str:
    """Calculate SHA256 hash of bytes."""
    return hashlib.sha256(b).hexdigest()


def extract_mac_from_topic(topic: str) -> str:
    """
    Extract device MAC address from topic.
    Topic format: ESP32CAM/{MAC}/data
    Returns MAC without colons (e.g., 'AABBCCDDEEFF')
    """
    parts = topic.split("/")
    if len(parts) >= 2:
        return parts[1]
    return "unknown"


def ensure_device(device_hw_id: str, last_ip: Optional[str] = None) -> str:
    """
    Upsert device by device_hw_id (MAC address without colons).
    Updates last_seen_at timestamp.
    Returns device_id (UUID).
    """
    try:
        # Check if device exists
        res = sb.table("devices")\
            .select("device_id")\
            .eq("device_hw_id", device_hw_id)\
            .limit(1)\
            .execute()

        if res.data:
            device_id = res.data[0]["device_id"]
            # Update last_seen_at
            update_data = {"last_seen_at": now_iso()}
            if last_ip:
                update_data["last_ip"] = last_ip
            sb.table("devices")\
                .update(update_data)\
                .eq("device_id", device_id)\
                .execute()
            log.debug("Device %s updated (device_id=%s)", device_hw_id, device_id)
            return device_id
        else:
            # Insert new device
            ins_data = {
                "device_hw_id": device_hw_id,
                "model": "ESP32S3-CAM",
                "last_seen_at": now_iso()
            }
            if last_ip:
                ins_data["last_ip"] = last_ip
            ins = sb.table("devices").insert(ins_data).execute()
            device_id = ins.data[0]["device_id"]
            log.info("New device registered: %s (device_id=%s)", device_hw_id, device_id)
            return device_id
    except Exception as e:
        log.error("ensure_device failed for %s: %s", device_hw_id, e)
        raise


def insert_device_status(device_id: str, status: str, raw: dict, pending: Optional[int] = None,
                        battery_mv: Optional[int] = None, wifi_rssi: Optional[int] = None,
                        uptime_ms: Optional[int] = None, boot_count: Optional[int] = None):
    """Insert device status record."""
    try:
        row = {
            "device_id": device_id,
            "status": status,
            "raw": raw
        }
        if pending is not None:
            row["pending_count"] = pending
        if battery_mv is not None:
            row["battery_mv"] = battery_mv
        if wifi_rssi is not None:
            row["wifi_rssi"] = wifi_rssi
        if uptime_ms is not None:
            row["uptime_ms"] = uptime_ms
        if boot_count is not None:
            row["boot_count"] = boot_count

        sb.table("device_status").insert(row).execute()
        log.debug("Device status inserted for %s: %s", device_id, status)
    except Exception as e:
        log.warning("device_status insert failed: %s", e)


def log_publish(device_id: Optional[str], topic: str, direction: str, payload_json: dict):
    """Log MQTT publish/subscribe to device_publish_log table."""
    try:
        sb.table("device_publish_log").insert({
            "device_id": device_id,
            "topic": topic,
            "direction": direction,
            "payload": payload_json
        }).execute()
    except Exception as e:
        log.warning("device_publish_log insert failed: %s", e)


def insert_error(device_id: str, capture_id: Optional[str], code: int, severity: str,
                message: str, details: dict):
    """Insert device error record."""
    try:
        sb.table("device_errors").insert({
            "device_id": device_id,
            "capture_id": capture_id,
            "error_code": code,
            "severity": severity,
            "message": message,
            "details": details
        }).execute()
        log.warning("Error %d logged for device %s: %s", code, device_id, message)
    except Exception as e:
        log.error("device_errors insert failed: %s", e)


def upsert_capture_from_metadata(device_id: str, meta: dict) -> Tuple[str, dict]:
    """
    Create or update a 'captures' row from metadata message.

    Firmware metadata format:
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

    Returns: (capture_id, capture_row_dict)
    """
    image_name = meta.get("image_name")
    image_size = meta.get("image_size")
    chunk_size = meta.get("max_chunks_size")  # Note: firmware uses "max_chunks_size" not "max_chunk_size"
    total_chunks = meta.get("total_chunk_count")
    captured_at = meta.get("capture_timeStamp") or meta.get("capture_timestamp") or now_iso()

    if not image_name:
        raise ValueError("image_name is required in metadata")

    cap_row = {
        "device_id": device_id,
        "device_capture_id": image_name,
        "captured_at": captured_at,
        "image_bytes": image_size,
        "chunk_size_bytes": chunk_size,
        "total_chunks": total_chunks,
        "img_format": "jpeg",
        "ingest_status": "assembling",
        "ingest_meta": meta
    }

    try:
        # Check if capture already exists (upsert by device_id + device_capture_id)
        existing = sb.table("captures")\
            .select("capture_id")\
            .eq("device_id", device_id)\
            .eq("device_capture_id", image_name)\
            .limit(1)\
            .execute()

        if existing.data:
            capture_id = existing.data[0]["capture_id"]
            sb.table("captures").update(cap_row).eq("capture_id", capture_id).execute()
            log.debug("Capture updated: %s (capture_id=%s)", image_name, capture_id)
            return capture_id, cap_row
        else:
            ins = sb.table("captures").insert(cap_row).execute()
            capture_id = ins.data[0]["capture_id"]
            log.info("Capture created: %s (capture_id=%s)", image_name, capture_id)
            return capture_id, cap_row
    except Exception as e:
        log.error("upsert_capture_from_metadata failed: %s", e)
        raise


def insert_sensor_reading(device_id: str, capture_id: str, meta: dict):
    """
    Insert sensor reading from BME680.

    Firmware provides: temperature, humidity, pressure, gas_resistance
    """
    try:
        row = {
            "capture_id": capture_id,
            "device_id": device_id,
            "temperature_c": meta.get("temperature"),
            "humidity_pct": meta.get("humidity"),
            "pressure_hpa": meta.get("pressure"),
            "gas_kohm": meta.get("gas_resistance"),  # Schema has gas_kohm field
            "raw": meta
        }
        sb.table("sensor_readings").insert(row).execute()
        log.debug("Sensor reading inserted for capture %s", capture_id)
    except Exception as e:
        log.warning("sensor_readings insert failed: %s", e)


# ------------ Image Assembly State ------------
class ImageAssembly:
    """Manages state for assembling a chunked image from ESP32 device."""

    def __init__(self, device_hw_id: str, image_name: str, total_chunks: int,
                chunk_size: int, declared_size: int):
        self.device_hw_id = device_hw_id
        self.image_name = image_name
        self.total_chunks = int(total_chunks) if total_chunks else 0
        self.chunk_size = int(chunk_size) if chunk_size else 1024
        self.declared_size = int(declared_size) if declared_size else 0
        self.t0 = time.time()
        self.bitset = [False] * max(self.total_chunks, 1)
        self.chunks: Dict[int, bytes] = {}
        self.retries = 0
        self.last_nack_ts = 0.0
        self.capture_id: Optional[str] = None

    def add_chunk(self, chunk_id: int, chunk_bytes: bytes):
        """Add a chunk to the assembly (chunk_id is 0-indexed in firmware)."""
        if 0 <= chunk_id < self.total_chunks:
            if not self.bitset[chunk_id]:
                self.bitset[chunk_id] = True
                self.chunks[chunk_id] = chunk_bytes
                log.debug("[%s] Chunk %d/%d received (%d bytes)",
                         self.device_hw_id, chunk_id + 1, self.total_chunks, len(chunk_bytes))

    def is_complete(self) -> bool:
        """Check if all chunks have been received."""
        return all(self.bitset)

    def get_missing_chunks(self) -> list:
        """Return list of missing chunk IDs (0-indexed)."""
        return [i for i, received in enumerate(self.bitset) if not received]

    def is_expired(self) -> bool:
        """Check if assembly has timed out."""
        return (time.time() - self.t0) * 1000 > CAPTURE_TIMEOUT_MS

    def assemble_image(self) -> bytes:
        """Concatenate all chunks in order to produce final image."""
        if not self.is_complete():
            raise ValueError("Cannot assemble incomplete image")
        return b"".join(self.chunks[i] for i in range(self.total_chunks))


# Global assembly state: key = (device_hw_id, image_name)
assemblies: Dict[Tuple[str, str], ImageAssembly] = {}


# ------------ MQTT Topic Helpers ------------
def build_ack_topic(device_hw_id: str) -> str:
    """Build ACK topic for a specific device: ESP32CAM/{MAC}/ack"""
    return f"ESP32CAM/{device_hw_id}/ack"


def build_cmd_topic(device_hw_id: str) -> str:
    """Build CMD topic for a specific device: ESP32CAM/{MAC}/cmd"""
    return f"ESP32CAM/{device_hw_id}/cmd"


def publish_missing_chunks_nack(client: mqtt.Client, device_hw_id: str,
                                image_name: str, missing_chunks: list):
    """
    Publish NACK with missing chunks list to device ACK topic.

    Format expected by firmware:
    {
      "image_name": "image_123.jpg",
      "missing_chunks": [5, 12, 23]
    }
    """
    topic = build_ack_topic(device_hw_id)
    payload = {
        "image_name": image_name,
        "missing_chunks": missing_chunks
    }
    client.publish(topic, json.dumps(payload), qos=1, retain=False)
    log_publish(None, topic, "out", payload)
    log.warning("[%s] NACK sent - missing chunks: %s (showing first 10)",
               device_hw_id, missing_chunks[:10])


def publish_ack_ok(client: mqtt.Client, device_hw_id: str, image_name: str,
                  next_wake_time: Optional[str] = None):
    """
    Publish ACK_OK to device indicating successful image receipt.

    Format expected by firmware:
    {
      "image_name": "image_123.jpg",
      "ACK_OK": {
        "next_wake_time": "5:30PM"  // optional
      }
    }
    """
    topic = build_ack_topic(device_hw_id)
    ack = {
        "image_name": image_name,
        "ACK_OK": {}
    }
    if next_wake_time:
        ack["ACK_OK"]["next_wake_time"] = next_wake_time

    client.publish(topic, json.dumps(ack), qos=1, retain=False)
    log_publish(None, topic, "out", ack)
    log.info("[%s] ACK_OK sent for image: %s", device_hw_id, image_name)


# ------------ MQTT Message Handlers ------------
def handle_status_message(client: mqtt.Client, topic: str, payload: bytes):
    """
    Handle device status message.

    Firmware format:
    {
      "device_id": "AABBCCDDEEFF",
      "status": "Alive",
      "pendingImg": 3
    }
    """
    device_hw_id = extract_mac_from_topic(topic)

    try:
        msg = json.loads(payload.decode("utf-8"))
    except Exception as e:
        log.error("[%s] Failed to parse status JSON: %s", device_hw_id, e)
        return

    device_id = ensure_device(device_hw_id)

    # Extract status fields
    status = msg.get("status", "unknown")
    pending_count = msg.get("pendingImg")

    # Insert status record
    insert_device_status(device_id, status, msg, pending=pending_count)
    log_publish(device_id, topic, "in", msg)

    log.info("[%s] Status: %s (pending: %s)", device_hw_id, status, pending_count)


def handle_data_message(client: mqtt.Client, topic: str, payload: bytes):
    """
    Handle device data message (metadata or chunk).

    Metadata format:
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

    Chunk format:
    {
      "device_id": "AABBCCDDEEFF",
      "image_name": "image_123.jpg",
      "chunk_id": 0,
      "max_chunk_size": 1024,
      "payload": "<base64-encoded-bytes>"
    }
    """
    device_hw_id = extract_mac_from_topic(topic)

    try:
        msg = json.loads(payload.decode("utf-8"))
    except Exception as e:
        log.error("[%s] Failed to parse data JSON: %s", device_hw_id, e)
        device_id = ensure_device(device_hw_id)
        insert_error(device_id, None, 2101, "error", "data_parse_error", {"error": str(e)})
        return

    device_id = ensure_device(device_hw_id)

    # Determine if this is metadata or chunk
    chunk_id = msg.get("chunk_id")
    image_name = msg.get("image_name")

    if chunk_id is None:
        # This is METADATA
        handle_metadata(client, device_id, device_hw_id, msg, topic)
    else:
        # This is a CHUNK
        handle_chunk(client, device_id, device_hw_id, msg, topic)


def handle_metadata(client: mqtt.Client, device_id: str, device_hw_id: str,
                   msg: dict, topic: str):
    """Handle image metadata message."""
    image_name = msg.get("image_name")

    # Log (but exclude large fields if any)
    log_msg = {k: v for k, v in msg.items() if k not in ["payload"]}
    log_publish(device_id, topic, "in", log_msg)

    try:
        # Create/update capture record
        capture_id, cap_row = upsert_capture_from_metadata(device_id, msg)

        # Insert sensor reading if sensor data present
        if any(k in msg for k in ["temperature", "humidity", "pressure", "gas_resistance"]):
            insert_sensor_reading(device_id, capture_id, msg)

        # Initialize assembly state
        key = (device_hw_id, image_name)
        if key not in assemblies:
            assemblies[key] = ImageAssembly(
                device_hw_id=device_hw_id,
                image_name=image_name,
                total_chunks=msg.get("total_chunk_count", 0),
                chunk_size=msg.get("max_chunks_size", 1024),
                declared_size=msg.get("image_size", 0)
            )
            assemblies[key].capture_id = capture_id
            log.info("[%s] Assembly started for %s (%d chunks, %d bytes)",
                    device_hw_id, image_name,
                    assemblies[key].total_chunks, assemblies[key].declared_size)
        else:
            # Metadata re-sent; update assembly parameters
            asm = assemblies[key]
            asm.declared_size = msg.get("image_size", asm.declared_size)
            asm.capture_id = capture_id

    except Exception as e:
        log.error("[%s] Failed to handle metadata: %s", device_hw_id, e)
        insert_error(device_id, None, 2100, "error", "metadata_processing_failed",
                    {"error": str(e), "metadata": msg})


def handle_chunk(client: mqtt.Client, device_id: str, device_hw_id: str,
                msg: dict, topic: str):
    """Handle image chunk message."""
    image_name = msg.get("image_name")
    chunk_id = msg.get("chunk_id")  # 0-indexed
    b64_payload = msg.get("payload")

    # Log without payload
    log_msg = {k: v for k, v in msg.items() if k != "payload"}
    log_msg["payload_length"] = len(b64_payload) if b64_payload else 0
    log_publish(device_id, topic, "in", log_msg)

    if not b64_payload:
        insert_error(device_id, None, 2102, "warn", "chunk_missing_payload",
                    {"image_name": image_name, "chunk_id": chunk_id})
        return

    try:
        chunk_bytes = base64.b64decode(b64_payload)
    except Exception as e:
        insert_error(device_id, None, 2103, "error", "chunk_b64_decode_error",
                    {"error": str(e), "chunk_id": chunk_id})
        return

    # Get or create assembly
    key = (device_hw_id, image_name)
    if key not in assemblies:
        # Chunk arrived before metadata - create minimal assembly
        log.warning("[%s] Chunk %d arrived before metadata for %s - creating minimal assembly",
                   device_hw_id, chunk_id, image_name)

        # Create minimal capture record
        try:
            capture_id, _ = upsert_capture_from_metadata(device_id, {
                "image_name": image_name,
                "image_size": msg.get("image_size"),
                "max_chunks_size": msg.get("max_chunk_size", 1024),
                "total_chunk_count": msg.get("total_chunks_count", chunk_id + 1),
                "capture_timeStamp": now_iso()
            })
        except Exception as e:
            log.error("[%s] Failed to create minimal capture: %s", device_hw_id, e)
            return

        assemblies[key] = ImageAssembly(
            device_hw_id=device_hw_id,
            image_name=image_name,
            total_chunks=msg.get("total_chunks_count", chunk_id + 1),
            chunk_size=msg.get("max_chunk_size", 1024),
            declared_size=msg.get("image_size", 0)
        )
        assemblies[key].capture_id = capture_id

    # Add chunk to assembly
    asm = assemblies[key]
    asm.add_chunk(chunk_id, chunk_bytes)


# ------------ Assembly Finalization ------------
def try_finalize_assemblies(client: mqtt.Client):
    """
    Periodically scan all active assemblies:
    - If complete: upload to storage, update DB, send ACK_OK
    - If incomplete & retry eligible: send NACK with missing chunks
    - If timed out: mark failed, clean up
    """
    now = time.time()
    to_delete = []

    for key, asm in list(assemblies.items()):
        device_hw_id, image_name = key

        # Check if complete
        if asm.is_complete():
            try:
                finalize_complete_assembly(client, asm, device_hw_id, image_name)
                to_delete.append(key)
            except Exception as e:
                log.error("[%s] Failed to finalize %s: %s", device_hw_id, image_name, e)
                device_id = ensure_device(device_hw_id)
                insert_error(device_id, asm.capture_id, 2200, "error",
                           "finalization_failed", {"error": str(e)})
                to_delete.append(key)
            continue

        # Not complete - check for retry or timeout
        missing = asm.get_missing_chunks()

        # Send NACK if eligible
        if (now - asm.last_nack_ts) * 1000 >= RETRANSMIT_DELAY_MS and asm.retries < RETRANSMIT_MAX:
            if missing:
                publish_missing_chunks_nack(client, device_hw_id, image_name, missing)
                asm.last_nack_ts = now
                asm.retries += 1

        # Check timeout
        if asm.is_expired():
            device_id = ensure_device(device_hw_id)
            insert_error(device_id, asm.capture_id, 2201, "error", "assembly_timeout",
                        {"missing_chunks": missing[:50], "total_missing": len(missing)})
            try:
                sb.table("captures").update({
                    "ingest_status": "failed",
                    "ingest_error": f"timeout - missing {len(missing)} chunks"
                }).eq("capture_id", asm.capture_id).execute()
            except Exception as e:
                log.error("Failed to update capture status: %s", e)

            log.error("[%s] Assembly timeout for %s (%d chunks missing)",
                     device_hw_id, image_name, len(missing))
            to_delete.append(key)

    # Clean up completed/failed assemblies
    for key in to_delete:
        assemblies.pop(key, None)


def finalize_complete_assembly(client: mqtt.Client, asm: ImageAssembly,
                               device_hw_id: str, image_name: str):
    """
    Finalize a complete image assembly:
    1. Concatenate chunks
    2. Validate JPEG signature and size
    3. Upload to Supabase Storage
    4. Update capture record
    5. Send ACK_OK to device
    """
    log.info("[%s] Finalizing complete assembly: %s", device_hw_id, image_name)

    # Assemble image
    img_bytes = asm.assemble_image()
    actual_size = len(img_bytes)

    device_id = ensure_device(device_hw_id)

    # Validate size
    if asm.declared_size and actual_size != asm.declared_size:
        log.warning("[%s] Size mismatch for %s - declared: %d, actual: %d",
                   device_hw_id, image_name, asm.declared_size, actual_size)
        insert_error(device_id, asm.capture_id, 2202, "warn", "size_mismatch",
                    {"declared": asm.declared_size, "actual": actual_size})

    # Validate JPEG signature (SOI: FF D8, EOI: FF D9)
    if not (len(img_bytes) >= 4 and
            img_bytes[0] == 0xFF and img_bytes[1] == 0xD8 and
            img_bytes[-2] == 0xFF and img_bytes[-1] == 0xD9):
        log.warning("[%s] Invalid JPEG signature for %s", device_hw_id, image_name)
        insert_error(device_id, asm.capture_id, 2203, "warn", "invalid_jpeg_signature", {})

    # Calculate SHA256
    img_sha = sha256_hex(img_bytes)

    # Upload to Supabase Storage
    # Path: captures/{device_hw_id}/YYYY/MM/DD/{image_name}
    ymd = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    storage_path = f"captures/{device_hw_id}/{ymd}/{image_name}"

    try:
        sb.storage.from_(STORAGE_BUCKET).upload(
            storage_path,
            img_bytes,
            {"content-type": "image/jpeg", "x-upsert": "true"}
        )
        log.info("[%s] Uploaded to storage: %s (%d bytes)", device_hw_id, storage_path, actual_size)
    except Exception as e:
        insert_error(device_id, asm.capture_id, 2204, "error", "storage_upload_failed",
                    {"error": str(e), "path": storage_path})
        raise

    # Get public URL (note: bucket is private, so this requires signed URL for access)
    # For now, store the path; UI can generate signed URLs as needed

    # Update capture record
    try:
        sb.table("captures").update({
            "ingest_status": "stored",
            "storage_path": storage_path,
            "image_sha256": img_sha,
            "image_bytes": actual_size
        }).eq("capture_id", asm.capture_id).execute()
        log.info("[%s] Capture record updated: %s", device_hw_id, asm.capture_id)
    except Exception as e:
        insert_error(device_id, asm.capture_id, 2205, "error", "capture_update_failed",
                    {"error": str(e)})
        raise

    # Send ACK_OK to device
    publish_ack_ok(client, device_hw_id, image_name)


# ------------ MQTT Client Lifecycle ------------
running = True

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    log.info("Shutdown signal received")
    running = False


def on_connect(client, userdata, flags, rc, properties=None):
    """MQTT connection callback."""
    if rc == 0:
        log.info("✓ MQTT connected successfully")
        # Subscribe to device topics
        client.subscribe(TOPIC_PATTERN_STATUS, qos=1)
        client.subscribe(TOPIC_PATTERN_DATA, qos=1)
        client.subscribe(TOPIC_PATTERN_ACK, qos=1)
        log.info("✓ Subscribed to topics:")
        log.info("  - %s", TOPIC_PATTERN_STATUS)
        log.info("  - %s", TOPIC_PATTERN_DATA)
        log.info("  - %s", TOPIC_PATTERN_ACK)
    else:
        log.error("✗ MQTT connection failed with code %d", rc)


def on_disconnect(client, userdata, rc, properties=None):
    """MQTT disconnection callback."""
    if rc != 0:
        log.warning("✗ MQTT disconnected unexpectedly (rc=%d) - will auto-reconnect", rc)
    else:
        log.info("✓ MQTT disconnected cleanly")


def on_message(client, userdata, msg: mqtt.MQTTMessage):
    """MQTT message callback - route to appropriate handler."""
    topic = msg.topic

    try:
        if "/status" in topic:
            handle_status_message(client, topic, msg.payload)
        elif "/data" in topic:
            handle_data_message(client, topic, msg.payload)
        elif "/ack" in topic:
            # Device->server ack (if firmware uses this); just log for now
            device_hw_id = extract_mac_from_topic(topic)
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                log.debug("[%s] ACK received: %s", device_hw_id, payload)
            except Exception:
                pass
    except Exception as e:
        log.error("Error handling message on %s: %s", topic, e)


def main():
    """Main worker loop."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    log.info("=" * 60)
    log.info("GXP MQTT Worker - ESP32S3-CAM Fleet Ingestion")
    log.info("=" * 60)
    log.info("MQTT Broker: %s:%d (TLS: %s)", MQTT_HOST, MQTT_PORT, MQTT_TLS)
    log.info("Supabase: %s", SUPABASE_URL)
    log.info("Storage Bucket: %s", STORAGE_BUCKET)
    log.info("=" * 60)

    # Create MQTT client
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"gxp-worker-{int(time.time())}"
    )

    # Configure TLS if enabled
    if MQTT_TLS:
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

    # Set credentials
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    # Set callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # Connect
    try:
        log.info("Connecting to MQTT broker...")
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except Exception as e:
        log.error("Failed to connect to MQTT broker: %s", e)
        return 1

    # Start MQTT loop in background thread
    client.loop_start()

    # Main processing loop
    try:
        log.info("✓ Worker started - processing messages...")
        while running:
            # Periodically check assemblies for completion/retry/timeout
            try_finalize_assemblies(client)
            time.sleep(0.5)
    except Exception as e:
        log.error("Unexpected error in main loop: %s", e)
    finally:
        log.info("Shutting down...")
        client.loop_stop()
        client.disconnect()
        log.info("✓ Shutdown complete")

    return 0


if __name__ == "__main__":
    exit(main())
