# picoA_primary.py  –  Head Node (Primary), Building E2
#
# Role: BLE gateway between the E2 classroom sensor mesh and the Pi 4 MQTT broker.
#
# What it does:
#   1. Scans BLE continuously for "C" (count) frames from sensor Picos.
#   2. Parses the data field  "E2-02-01:5"  to extract ROOM_ID and count.
#   3. Publishes occupancy JSON to the Pi 4 broker via MQTT over WiFi.
#   4. Does NOT relay BLE frames — that is the sensor Picos' job.
#   5. Publishes a retained "online" status on connect (LWT = "offline").
#
# MQTT topics published:
#   csc2106/HeadNode-E2/classroom/<ROOM_ID>/occupancy  ← picked up by bridge
#   csc2106/HeadNode-E2/status                         ← online/offline LWT

import bluetooth
import time
import ujson
import os
import ucryptolib
import network
import umqtt.simple as simple
from machine import Pin
from micropython import const

# ── BLE IRQ events ────────────────────────────────────────────────────────────
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE   = const(6)

# ── Config ────────────────────────────────────────────────────────────────────
WIFI_SSID     = "Danwifi"
WIFI_PASSWORD = "wifiisgood"
BROKER_IP     = "10.71.189.30"
MQTT_USER     = b"Pi4-HeadNode-E2"
MQTT_PASS     = b"e2-secret"
AES_KEY       = b"CSC2106-Group-04"  # 16 bytes — must match bridge
NODE_ID         = "HeadNode-E2"
CLIENT_ID       = ("Pi4-" + NODE_ID).encode()
BUILDING_PREFIX = "2"   # only accept BLE frames from sensors with room code starting "2xx" (E2)

STATUS_TOPIC  = "csc2106/{}/status".format(NODE_ID)

SCAN_MS       = 10_000   # scan window — restarts automatically on SCAN_DONE
SEEN_MAX      = 300      # dedup cache (larger than sensor Picos)

# ── WiFi ──────────────────────────────────────────────────────────────────────
def connect_wifi(ssid, password, timeout=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi: " + ssid)
        wlan.connect(ssid, password)
        for _ in range(timeout):
            if wlan.isconnected():
                break
            time.sleep(1)
        else:
            raise RuntimeError(
                "WiFi connection timed out — check SSID/password and that hotspot is ON"
            )
    print("WiFi connected:", wlan.ifconfig())

# ── MQTT ──────────────────────────────────────────────────────────────────────
def mqtt_connect():
    c = simple.MQTTClient(client_id=CLIENT_ID, server=BROKER_IP,
                          user=MQTT_USER, password=MQTT_PASS, keepalive=15)
    c.set_last_will(STATUS_TOPIC.encode(), b"offline", retain=True, qos=1)
    c.connect()
    c.publish(STATUS_TOPIC.encode(), b"online", retain=True, qos=1)
    print("[{}] MQTT connected — broker {}".format(NODE_ID, BROKER_IP))
    return c

# ── AES-CBC encryption ────────────────────────────────────────────────────────
def encrypt_payload(plaintext_str):
    """Encrypt a string with AES-128-CBC. Returns IV + ciphertext (bytes)."""
    iv = os.urandom(16)
    data = plaintext_str.encode()
    # PKCS7 pad to 16-byte boundary
    pad = 16 - (len(data) % 16)
    data += bytes([pad] * pad)
    cipher = ucryptolib.aes(AES_KEY, 2, iv)
    return iv + cipher.encrypt(data)

# ── BLE frame helpers ─────────────────────────────────────────────────────────
def decode_room_id(code):
    # Sensor Picos send a 4-char room code: building + floor + room.
    # "2201" → "E2-02-01",  "6203" → "E6-02-03"
    return "E{}-0{}-{}".format(code[0], code[1], code[2:])

def parse_frame(s):
    try:
        if not s.startswith("M1|"):
            return None
        parts = s.split("|", 5)
        if len(parts) != 6:
            return None
        _, orig, msgid, ttl_s, typ, data = parts
        return orig, msgid, int(ttl_s), typ, data
    except Exception:
        return None

# ── Head node class ───────────────────────────────────────────────────────────
class HeadNode:
    def __init__(self, mqtt_client):
        self.client  = mqtt_client
        self.seen    = []
        self._rx_buf = []   # frames queued by IRQ, processed in main loop

        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        self.ble.gap_scan(SCAN_MS, 30000, 30000)
        print("[{}] BLE scanning...".format(NODE_ID))

    # ── Dedup cache ───────────────────────────────────────────────────────────
    def _seen_check_add(self, key):
        if key in self.seen:
            return True
        self.seen.append(key)
        if len(self.seen) > SEEN_MAX:
            del self.seen[0: len(self.seen) - SEEN_MAX]
        return False

    # ── BLE IRQ (keep short — no MQTT I/O here) ───────────────────────────────
    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            addr_type, addr, adv_type, rssi, adv_data = data
            try:
                raw = bytes(adv_data)
                idx = raw.find(b"M1|")
                if idx == -1:
                    return
                s = raw[idx:].decode("utf-8", "ignore").split("\x00")[0]
            except Exception:
                return

            parsed = parse_frame(s)
            if not parsed:
                return

            orig, msgid, ttl, typ, payload = parsed

            if typ not in ("C", "H"):
                return

            # Filter: only process frames from this building's sensors
            if not payload.startswith(BUILDING_PREFIX):
                return

            key = "{}:{}".format(orig, msgid)
            if self._seen_check_add(key):
                return   # duplicate — already processed

            # Queue (type, data) for main-loop MQTT publish
            self._rx_buf.append((typ, payload))

        elif event == _IRQ_SCAN_DONE:
            self.ble.gap_scan(SCAN_MS, 30000, 30000)

    # ── Publish occupancy to MQTT broker ──────────────────────────────────────
    def _publish(self, data_field):
        # data_field format: "2201:5"  (4-char room code + count)
        try:
            room_code, count_str = data_field.split(":", 1)
            room_id = decode_room_id(room_code)   # "2201" → "E2-02-01"
            count   = int(count_str)
        except Exception:
            print("[{}] bad data field: {}".format(NODE_ID, data_field))
            return

        topic = "csc2106/{}/classroom/{}/occupancy".format(NODE_ID, room_id)
        msg   = ujson.dumps({
            "room_id":   room_id,
            "count":     count,
            "timestamp": time.time(),
        })
        led.on()
        try:
            self.client.publish(topic.encode(), encrypt_payload(msg), qos=1)
            print("[{}] → {} count={}".format(NODE_ID, room_id, count))
        except OSError as e:
            print("[{}] MQTT publish failed:".format(NODE_ID), e)
            raise   # bubble up so run() can reconnect
        finally:
            led.off()

    # ── Publish heatmap to MQTT broker ────────────────────────────────────────
    def _publish_heatmap(self, data_field):
        # data_field format: "2201:A5"  (4-char room code + 2-hex packed byte)
        try:
            room_code, hex_str = data_field.split(":", 1)
            room_id = decode_room_id(room_code)   # "2201" → "E2-02-01"
            packed  = int(hex_str, 16)
        except Exception:
            print("[{}] bad heatmap field: {}".format(NODE_ID, data_field))
            return

        z1 = (packed >> 6) & 0x3
        z2 = (packed >> 4) & 0x3
        z3 = (packed >> 2) & 0x3
        z4 =  packed       & 0x3

        topic = "csc2106/{}/classroom/{}/heatmap".format(NODE_ID, room_id)
        msg   = ujson.dumps({
            "room_id":   room_id,
            "zones":     [z1, z2, z3, z4],
            "timestamp": time.time(),
        })
        led.on()
        try:
            self.client.publish(topic.encode(), encrypt_payload(msg), qos=1)
            print("[{}] HMAP → {} zones=[{},{},{},{}]".format(NODE_ID, room_id, z1, z2, z3, z4))
        except OSError as e:
            print("[{}] MQTT heatmap publish failed:".format(NODE_ID), e)
            raise
        finally:
            led.off()

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self):
        last_ping = time.ticks_ms()
        while True:
            # Send keepalive ping every 10s to prevent broker timeout (keepalive=15)
            if time.ticks_diff(time.ticks_ms(), last_ping) >= 10_000:
                try:
                    self.client.ping()
                except OSError:
                    pass
                last_ping = time.ticks_ms()

            # Drain BLE receive buffer and publish each frame
            while self._rx_buf:
                typ, payload = self._rx_buf.pop(0)
                try:
                    if typ == "C":
                        self._publish(payload)
                    elif typ == "H":
                        self._publish_heatmap(payload)
                except OSError:
                    print("[{}] MQTT error, reconnecting...".format(NODE_ID))
                    time.sleep(5)
                    try:
                        self.client = mqtt_connect()
                    except Exception:
                        pass

            # Keep MQTT connection alive (handles keepalive ping)
            try:
                self.client.check_msg()
            except OSError:
                print("[{}] MQTT keepalive error, reconnecting...".format(NODE_ID))
                time.sleep(5)
                try:
                    self.client = mqtt_connect()
                except Exception:
                    pass

            time.sleep_ms(10)

# ── Boot ──────────────────────────────────────────────────────────────────────
connect_wifi(WIFI_SSID, WIFI_PASSWORD)
led    = Pin("LED", Pin.OUT)
client = mqtt_connect()

node = HeadNode(client)
node.run()
