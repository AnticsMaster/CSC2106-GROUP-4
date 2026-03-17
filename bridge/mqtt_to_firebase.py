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
import threading

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

MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "172.20.10.2")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
FIREBASE_CREDS = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    "iot-project-95f1e-firebase-adminsdk-fbsvc-a0a77f081e.json",
)

OCCUPANCY_TOPIC = "csc2106/+/classroom/+/occupancy"
STATUS_TOPIC = "csc2106/+/classroom/+/status"

# ── Capacity defaults ───────────────────────────────────────────────────────────
# These seed Firestore on first run if no settings/capacity document exists yet.
# After that, edit capacity live from the dashboard — changes apply immediately
# without restarting the bridge.
DEFAULT_CAPACITY = 20

CAPACITY_DEFAULTS: dict[str, int] = {
    "E2-02-01": 20,
    "E2-02-02": 20,
    "E2-02-03": 20,
    "E6-02-01": 20,
    "E6-02-02": 20,
    "E6-02-03": 20,
}

# Live cache — updated by Firestore snapshot listener (runs in a background thread).
# Protected by a lock since MQTT callbacks and the Firestore listener run concurrently.
_capacity_cache: dict[str, int] = {}
_capacity_lock  = threading.Lock()

# ── Firebase ───────────────────────────────────────────────────────────────────
if not os.path.isfile(FIREBASE_CREDS):
    log.error("Firebase credentials not found: %s", FIREBASE_CREDS)
    log.error("Download a service-account key from the Firebase console")
    sys.exit(1)

cred = credentials.Certificate(FIREBASE_CREDS)
firebase_admin.initialize_app(cred)
db = firestore.client()
log.info("Firestore ready")


def _on_capacity_snapshot(doc_snapshot, _changes, _read_time):
    """Called by Firestore whenever settings/capacity changes.
    Runs in a background thread — updates _capacity_cache under lock."""
    global _capacity_cache
    for doc in doc_snapshot:
        new_cache = {k: int(v) for k, v in doc.to_dict().items() if isinstance(v, (int, float))}
        with _capacity_lock:
            _capacity_cache = new_cache
        log.info("Capacity settings refreshed from Firestore: %s", new_cache)


def _init_capacity():
    """Seed Firestore with defaults if no document exists, then start listener."""
    cap_ref = db.collection("settings").document("capacity")
    snap    = cap_ref.get()

    if not snap.exists:
        cap_ref.set(CAPACITY_DEFAULTS)
        log.info("Created settings/capacity in Firestore with defaults: %s", CAPACITY_DEFAULTS)
        with _capacity_lock:
            _capacity_cache.update(CAPACITY_DEFAULTS)
    else:
        with _capacity_lock:
            _capacity_cache.update({k: int(v) for k, v in snap.to_dict().items()})
        log.info("Loaded capacity from Firestore: %s", _capacity_cache)

    # Real-time listener — fires _on_capacity_snapshot on any change
    cap_ref.on_snapshot(_on_capacity_snapshot)
    log.info("Watching settings/capacity for live updates")


_init_capacity()


# ── Helpers ────────────────────────────────────────────────────────────────────
def upsert_classroom(room_id: str, data: dict) -> None:
    db.collection("classrooms").document(room_id).set(data, merge=True)


def append_history(data: dict) -> None:
    db.collection("occupancy_history").add(data)


# ── MQTT callbacks ─────────────────────────────────────────────────────────────
def on_connect(client, _userdata, _flags, rc):
    if rc != 0:
        log.error("MQTT connect failed (rc=%d)", rc)
        return
    log.info("MQTT connected to %s:%d", MQTT_BROKER_IP, MQTT_PORT)
    client.subscribe(OCCUPANCY_TOPIC, qos=1)
    client.subscribe(STATUS_TOPIC, qos=1)
    log.info("Subscribed: %s, %s", OCCUPANCY_TOPIC, STATUS_TOPIC)


def on_disconnect(_client, _userdata, rc):
    if rc != 0:
        log.warning("Unexpected disconnect (rc=%d), will reconnect", rc)


def on_message(_client, _userdata, msg):
    topic = msg.topic
    raw = msg.payload.decode("utf-8", errors="replace")
    log.info("MSG  %s  ->  %s", topic, raw)

    parts = topic.split("/")
    if len(parts) < 5:
        return

    room_id = parts[3]
    msg_type = parts[4]

    if msg_type == "occupancy":
        _handle_occupancy(room_id, raw)
    elif msg_type == "status":
        _handle_status(room_id, raw)


def _handle_occupancy(room_id: str, raw: str) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.error("[%s] Bad JSON: %s", room_id, raw)
        return

    count     = int(data.get("count", 0))
    room_name = data.get("room_name", room_id)
    pico_ts   = data.get("timestamp", 0)
    now       = firestore.SERVER_TIMESTAMP

    # ── Capacity logic — live from Firestore (dashboard-editable) ─────────────
    with _capacity_lock:
        capacity = _capacity_cache.get(room_id, DEFAULT_CAPACITY)

    if count == 0:
        capacity_status = "empty"
    elif count < capacity:
        capacity_status = "occupied"
    elif count == capacity:
        capacity_status = "at_capacity"
    else:
        capacity_status = "over_capacity"

    occupied    = count > 0
    at_capacity = count >= capacity

    upsert_classroom(
        room_id,
        {
            "roomId":         room_id,
            "roomName":       room_name,
            "occupied":       occupied,
            "count":          count,
            "capacity":       capacity,
            "atCapacity":     at_capacity,
            "capacityStatus": capacity_status,   # "empty" | "occupied" | "at_capacity" | "over_capacity"
            "lastUpdated":    now,
            "picoTimestamp":  pico_ts,
        },
    )

    append_history(
        {
            "roomId":         room_id,
            "roomName":       room_name,
            "occupied":       occupied,
            "count":          count,
            "capacity":       capacity,
            "capacityStatus": capacity_status,
            "timestamp":      now,
            "picoTimestamp":  pico_ts,
        }
    )

    log.info(
        "[%s] Firestore updated  count=%d/%d  status=%s",
        room_id, count, capacity, capacity_status,
    )


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
