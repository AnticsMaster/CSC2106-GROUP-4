#!/usr/bin/env python3
"""
MQTT-to-Firebase Bridge
───────────────────────
Runs on a PC on the same LAN as the Pico W MQTT broker.
Subscribes to classroom occupancy topics and writes data to
Firebase Firestore in real time.

Collections maintained:
  classrooms/<room_id>          current state (upserted)
  occupancy_history/<auto-id>   append-only time-series

Usage:
  pip install -r requirements.txt
  cp .env.example .env          # fill in your values
  python mqtt_to_firebase.py
"""

import json
import os
import sys
import time
import logging
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

import paho.mqtt.client as mqtt
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bridge")

# ── Config ─────────────────────────────────────────────────────────────────────
load_dotenv()

MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "10.114.66.30")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", "bridge")
MQTT_PASS = os.getenv("MQTT_PASS", "bridge-secret")
AES_KEY = b"CSC2106-Group-04"  # 16 bytes — must match all Pico nodes
FIREBASE_CREDS = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    "iot-project-95f1e-firebase-adminsdk-fbsvc-a0a77f081e.json",
)

OCCUPANCY_TOPIC = "csc2106/+/classroom/+/occupancy"
HEATMAP_TOPIC   = "csc2106/+/classroom/+/heatmap"
STATUS_TOPIC    = "csc2106/+/classroom/+/status"

# ── Firebase ───────────────────────────────────────────────────────────────────
if not os.path.isfile(FIREBASE_CREDS):
    log.error("Firebase credentials not found: %s", FIREBASE_CREDS)
    log.error("Download a service-account key from the Firebase console")
    sys.exit(1)

cred = credentials.Certificate(FIREBASE_CREDS)
firebase_admin.initialize_app(cred)
db = firestore.client()
log.info("Firestore ready")


# ── Helpers ────────────────────────────────────────────────────────────────────
DEFAULT_MAX_OCCUPANCY = 30


def decrypt_payload(data: bytes) -> bytes:
    """Decrypt AES-128-CBC payload from Pico nodes (IV prepended)."""
    iv, ct = data[:16], data[16:]
    return unpad(AES.new(AES_KEY, AES.MODE_CBC, iv).decrypt(ct), 16)


def upsert_classroom(room_id: str, data: dict, snap=None) -> None:
    ref = db.collection("classrooms").document(room_id)
    if snap is None:
        snap = ref.get()
    if not snap.exists or snap.get("maxOccupancy") is None:
        data.setdefault("maxOccupancy", DEFAULT_MAX_OCCUPANCY)
    ref.set(data, merge=True)


def append_history(data: dict) -> None:
    db.collection("occupancy_history").add(data)


# ── MQTT callbacks ─────────────────────────────────────────────────────────────
def on_connect(client, _userdata, _flags, rc):
    if rc != 0:
        log.error("MQTT connect failed (rc=%d)", rc)
        return
    log.info("MQTT connected to %s:%d", MQTT_BROKER_IP, MQTT_PORT)
    client.subscribe(OCCUPANCY_TOPIC, qos=1)
    client.subscribe(HEATMAP_TOPIC, qos=1)
    client.subscribe(STATUS_TOPIC, qos=1)
    log.info("Subscribed: %s, %s, %s", OCCUPANCY_TOPIC, HEATMAP_TOPIC, STATUS_TOPIC)


def on_disconnect(_client, _userdata, rc):
    if rc != 0:
        log.warning("Unexpected disconnect (rc=%d), will reconnect", rc)


def on_message(_client, _userdata, msg):
    topic = msg.topic
    parts = topic.split("/")
    if len(parts) < 5:
        return

    room_id = parts[3]
    msg_type = parts[4]

    if msg_type == "occupancy":
        log.info("MSG  %s  ->  <encrypted %d bytes>", topic, len(msg.payload))
        _handle_occupancy(room_id, msg.payload)
    elif msg_type == "heatmap":
        log.info("MSG  %s  ->  <encrypted %d bytes>", topic, len(msg.payload))
        _handle_heatmap(room_id, msg.payload)
    elif msg_type == "status":
        raw = msg.payload.decode("utf-8", errors="replace")
        log.info("MSG  %s  ->  %s", topic, raw)
        _handle_status(room_id, raw)


def _handle_occupancy(room_id: str, raw_bytes: bytes) -> None:
    try:
        decrypted = decrypt_payload(raw_bytes)
        data = json.loads(decrypted)
        log.info("[%s] Decrypted: %s", room_id, decrypted.decode())
    except Exception as e:
        log.error("[%s] Decrypt/parse error: %s", room_id, e)
        return

    count = int(data.get("count", 0))
    room_name = data.get("room_name", room_id)
    pico_ts = data.get("timestamp", 0)
    now = firestore.SERVER_TIMESTAMP

    # Derive occupied from Firestore maxOccupancy (single read, reused for upsert)
    snap = db.collection("classrooms").document(room_id).get()
    max_occ = DEFAULT_MAX_OCCUPANCY
    if snap.exists and snap.get("maxOccupancy") is not None:
        max_occ = int(snap.get("maxOccupancy"))
    occupied = count > max_occ

    upsert_classroom(
        room_id,
        {
            "roomId": room_id,
            "roomName": room_name,
            "occupied": occupied,
            "count": count,
            "lastUpdated": now,
            "picoTimestamp": pico_ts,
        },
        snap=snap,
    )

    append_history(
        {
            "roomId": room_id,
            "roomName": room_name,
            "occupied": occupied,
            "count": count,
            "timestamp": now,
            "picoTimestamp": pico_ts,
        }
    )

    log.info("[%s] Firestore updated  occupied=%s  count=%d  max=%d", room_id, occupied, count, max_occ)


def _handle_heatmap(room_id: str, raw_bytes: bytes) -> None:
    try:
        decrypted = decrypt_payload(raw_bytes)
        data = json.loads(decrypted)
        log.info("[%s] Heatmap decrypted: %s", room_id, decrypted.decode())
    except Exception as e:
        log.error("[%s] Heatmap decrypt/parse error: %s", room_id, e)
        return

    zones = data.get("zones", [0, 0, 0, 0])   # list of 4 scores (0–3)
    pico_ts = data.get("timestamp", 0)
    now = firestore.SERVER_TIMESTAMP

    # Map numeric scores to readable labels for the dashboard
    SCORE_LABELS = {0: "none", 1: "low", 2: "medium", 3: "high"}
    zone_labels = [SCORE_LABELS.get(s, "none") for s in zones]

    heatmap_doc = {
        "zones": zones,
        "zoneLabels": zone_labels,
        "lastUpdated": now,
        "picoTimestamp": pico_ts,
    }

    # Merge into classrooms/<room_id> so the dashboard can read it alongside occupancy
    upsert_classroom(room_id, {"heatmap": heatmap_doc})

    # Also append to heatmap_history for time-series analytics
    db.collection("heatmap_history").add({
        "roomId": room_id,
        "zones": zones,
        "zoneLabels": zone_labels,
        "timestamp": now,
        "picoTimestamp": pico_ts,
    })

    log.info("[%s] Heatmap Firestore updated  zones=%s", room_id, zones)


def _handle_status(room_id: str, raw: str) -> None:
    status = raw.strip().lower()
    upsert_classroom(
        room_id,
        {
            "deviceStatus": status,
            "lastSeen": firestore.SERVER_TIMESTAMP,
        },
    )
    log.info("[%s] device -> %s", room_id, status)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    log.info("=== CSC2106 MQTT -> Firebase Bridge ===")
    log.info("Broker: %s:%d", MQTT_BROKER_IP, MQTT_PORT)

    client = mqtt.Client(client_id="bridge", protocol=mqtt.MQTTv311)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    while True:
        try:
            client.connect(MQTT_BROKER_IP, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except ConnectionRefusedError:
            log.error("Connection refused - is the broker running?")
        except OSError as exc:
            log.error("Network error: %s", exc)
        log.info("Retrying in 10s...")
        time.sleep(10)


if __name__ == "__main__":
    main()
