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

MQTT_BROKER_IP = os.getenv("MQTT_BROKER_IP", "10.236.91.21")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
FIREBASE_CREDS = os.getenv("FIREBASE_CREDENTIALS_PATH", "iot-project-95f1e-firebase-adminsdk-fbsvc-a0a77f081e.json")

OCCUPANCY_TOPIC = "csc2106/classroom/+/occupancy"
STATUS_TOPIC = "csc2106/classroom/+/status"

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
    if len(parts) < 4:
        return

    room_id = parts[2]
    msg_type = parts[3]

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

    occupied = bool(data.get("occupied", False))
    count = int(data.get("count", 0))
    room_name = data.get("room_name", room_id)
    pico_ts = data.get("timestamp", 0)
    now = firestore.SERVER_TIMESTAMP

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

    log.info("[%s] Firestore updated  occupied=%s  count=%d", room_id, occupied, count)


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
