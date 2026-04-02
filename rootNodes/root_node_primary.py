# root_node_primary.py  –  Unified Head Node (Primary), config-driven
#
# Role: BLE gateway between a classroom sensor mesh and the Pi 4 MQTT broker.
#
# ── HOW TO DEPLOY TO A NEW BUILDING ──────────────────────────────────────────
# 1. Copy this file to the Pico (no changes needed).
# 2. Create config.json on the Pico's flash:
#
#      {
#        "wifi_ssid":       "YourWiFi",
#        "wifi_password":   "YourPassword",
#        "broker_ip":       "10.114.66.30",
#        "node_id":         "HeadNode-E3",
#        "mqtt_pass":       "e3-secret",
#        "building_prefix": "3",
#        "aes_key":         "CSC2106-Group-04"
#      }
#
#    Rules:
#      - node_id format:         "HeadNode-E<building_number>"
#      - mqtt_pass convention:   "e<building_number>-secret"
#      - building_prefix:        the building number digit(s), e.g. "3" for E3
#      - aes_key must match the bridge's AES key (16 bytes)
# 3. Power on. The broker accepts it automatically via pattern-based ACL.
# ─────────────────────────────────────────────────────────────────────────────

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

SCAN_MS  = 10_000
SEEN_MAX = 300

# ── Load config ───────────────────────────────────────────────────────────────
def load_config():
    try:
        with open("config.json") as f:
            return ujson.load(f)
    except Exception:
        raise RuntimeError("Missing config.json on this Pico's flash")

cfg = load_config()

WIFI_SSID       = cfg["wifi_ssid"]
WIFI_PASSWORD   = cfg["wifi_password"]
BROKER_IP       = cfg["broker_ip"]
NODE_ID         = cfg["node_id"]           # e.g. "HeadNode-E3"
MQTT_USER       = ("Pi4-" + NODE_ID).encode()
MQTT_PASS       = cfg["mqtt_pass"].encode()
AES_KEY         = cfg.get("aes_key", "CSC2106-Group-04").encode()
BUILDING_PREFIX = cfg["building_prefix"]   # e.g. "3" — only relay BLE from E3 sensors

CLIENT_ID    = MQTT_USER
STATUS_TOPIC = "csc2106/{}/status".format(NODE_ID)

# ── WiFi ──────────────────────────────────────────────────────────────────────
def connect_wifi(timeout=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi:", WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(timeout):
            if wlan.isconnected():
                break
            time.sleep(1)
        else:
            raise RuntimeError("WiFi timed out — check SSID/password")
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
    iv   = os.urandom(16)
    data = plaintext_str.encode()
    pad  = 16 - (len(data) % 16)
    data += bytes([pad] * pad)
    cipher = ucryptolib.aes(AES_KEY, 2, iv)
    return iv + cipher.encrypt(data)

# ── BLE frame helpers ─────────────────────────────────────────────────────────
def decode_room_id(code):
    # 4-char room code → full room ID
    # "2201" → "E2-02-01",  "3301" → "E3-03-01"
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
        self._rx_buf = []

        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        self.ble.gap_scan(SCAN_MS, 30000, 30000)
        print("[{}] BLE scanning... (building prefix: {})".format(NODE_ID, BUILDING_PREFIX))

    def _seen_check_add(self, key):
        if key in self.seen:
            return True
        self.seen.append(key)
        if len(self.seen) > SEEN_MAX:
            del self.seen[0: len(self.seen) - SEEN_MAX]
        return False

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

            # Only process frames from this building's sensors
            if not payload.startswith(BUILDING_PREFIX):
                return

            key = "{}:{}".format(orig, msgid)
            if self._seen_check_add(key):
                return

            self._rx_buf.append((typ, payload))

        elif event == _IRQ_SCAN_DONE:
            self.ble.gap_scan(SCAN_MS, 30000, 30000)

    def _publish(self, data_field):
        try:
            room_code, count_str = data_field.split(":", 1)
            room_id = decode_room_id(room_code)
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
            raise
        finally:
            led.off()

    def _publish_heatmap(self, data_field):
        try:
            room_code, hex_str = data_field.split(":", 1)
            room_id = decode_room_id(room_code)
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

    def run(self):
        last_ping = time.ticks_ms()
        while True:
            if time.ticks_diff(time.ticks_ms(), last_ping) >= 10_000:
                try:
                    self.client.ping()
                except OSError:
                    pass
                last_ping = time.ticks_ms()

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
connect_wifi()
led    = Pin("LED", Pin.OUT)
client = mqtt_connect()

node = HeadNode(client)
node.run()
