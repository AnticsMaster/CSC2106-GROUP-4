# root_node_backup_fixed.py  –  Unified Head Node (Backup), config-driven, secure BLE

import bluetooth
import time
import ujson
import os
import ucryptolib
import uhashlib
import network
import umqtt.simple as simple
from machine import Pin
from micropython import const

_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE   = const(6)

SCAN_MS  = 10_000
SEEN_MAX = 300

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
NODE_ID         = cfg["node_id"]
PRIMARY_ID      = cfg["primary_id"]
MQTT_USER       = ("Pi4-" + NODE_ID).encode()
MQTT_PASS       = cfg["mqtt_pass"].encode()
AES_KEY         = cfg.get("aes_key", "CSC2106-Group-04").encode()
BUILDING_PREFIX = str(cfg["building_prefix"])

CLIENT_ID            = MQTT_USER
STATUS_TOPIC         = "csc2106/{}/status".format(NODE_ID)
PRIMARY_STATUS_TOPIC = "csc2106/{}/status".format(PRIMARY_ID)

PROTOCOL_VERSION = 0xA1
BLE_ENC_KEY = cfg["ENC"].encode()
BLE_MAC_KEY = cfg["MAC"].encode() 
COMPANY_ID = bytes.fromhex(cfg["company_id"])
TYPE_COUNT   = 0x1
TYPE_HEATMAP = 0x2

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

def mqtt_connect(on_msg_cb):
    c = simple.MQTTClient(client_id=CLIENT_ID, server=BROKER_IP, user=MQTT_USER, password=MQTT_PASS, keepalive=60)
    c.set_last_will(STATUS_TOPIC.encode(), b"offline", retain=True, qos=1)
    c.set_callback(on_msg_cb)
    c.connect()
    c.publish(STATUS_TOPIC.encode(), b"online", retain=True, qos=1)
    c.subscribe(PRIMARY_STATUS_TOPIC.encode(), qos=1)
    print("[{}] MQTT connected — broker {}".format(NODE_ID, BROKER_IP))
    print("[{}] Monitoring primary: {}".format(NODE_ID, PRIMARY_STATUS_TOPIC))
    return c

def encrypt_payload(plaintext_str):
    iv = os.urandom(16)
    data = plaintext_str.encode()
    pad = 16 - (len(data) % 16)
    data += bytes([pad] * pad)
    cipher = ucryptolib.aes(AES_KEY, 2, iv)
    return iv + cipher.encrypt(data)

def unpack_classroom_id(packed):
    value = int.from_bytes(packed, "big")
    is_west = (value >> 12) & 0x1
    block_num = (value >> 9) & 0x7
    level = (value >> 5) & 0xF
    room_num = value & 0x1F
    return is_west, block_num, level, room_num

def classroom_fields_to_room_id(is_west, block_num, level, room_num):
    prefix = "W" if is_west else "E"
    return "{}{}-{:02d}-{:02d}".format(prefix, block_num, level, room_num)

def build_nonce(unique_id, msgid, ttl_type):
    return unique_id + int(msgid).to_bytes(2, "big") + bytes([ttl_type & 0xFF]) + bytes(5)

def aes_keystream(unique_id, msgid, ttl_type):
    nonce = build_nonce(unique_id, msgid, ttl_type)
    aes = ucryptolib.aes(BLE_ENC_KEY, 1)
    return aes.encrypt(nonce)

def decrypt_data(ciphertext, unique_id, msgid, ttl_type):
    ks = aes_keystream(unique_id, msgid, ttl_type)
    return bytes([c ^ ks[i] for i, c in enumerate(ciphertext)])

def compute_auth_tag(header, ciphertext):
    h = uhashlib.sha256()
    h.update(BLE_MAC_KEY)
    h.update(header)
    h.update(ciphertext)
    return h.digest()[:4]

def parse_frame(frame):
    if len(frame) != 20 or frame[0] != PROTOCOL_VERSION:
        return None
    unique_id = frame[1:9]
    msgid = int.from_bytes(frame[9:11], "big")
    ttl_type = frame[11]
    ttl = (ttl_type >> 4) & 0xF
    typ = ttl_type & 0xF
    ciphertext = frame[12:16]
    tag = frame[16:20]
    header = frame[:12]
    if tag != compute_auth_tag(header, ciphertext):
        return None
    return unique_id, msgid, ttl, typ, ciphertext, ttl_type

def extract_secure_frame_from_adv(adv_data):
    raw = bytes(adv_data)
    i = 0
    n = len(raw)
    while i < n:
        ln = raw[i]
        if ln == 0:
            break
        j = i + 1
        ad_type = raw[j]
        field = raw[j + 1 : i + 1 + ln]
        if ad_type == 0xFF and len(field) >= 22 and field[:2] == COMPANY_ID:
            frame = field[2:22]
            if len(frame) == 20:
                return frame
        i += ln + 1
    return None

class BackupHeadNode:
    def __init__(self):
        self.client = None
        self.seen = []
        self._rx_buf = []
        self.is_active = False

        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        self.ble.gap_scan(SCAN_MS, 30000, 30000)
        print("[{}] BLE scanning (STANDBY — waiting for primary to fail)".format(NODE_ID))

    def on_mqtt_msg(self, topic, msg):
        if topic.decode() != PRIMARY_STATUS_TOPIC:
            return
        status = msg.decode()
        if status == "offline" and not self.is_active:
            self.is_active = True
            print("[{}] Primary OFFLINE — activating".format(NODE_ID))
        elif status == "online" and self.is_active:
            self.is_active = False
            self._rx_buf.clear()
            print("[{}] Primary ONLINE — returning to standby".format(NODE_ID))

    def _seen_check_add(self, key):
        if key in self.seen:
            return True
        self.seen.append(key)
        if len(self.seen) > SEEN_MAX:
            del self.seen[0: len(self.seen) - SEEN_MAX]
        return False

    def _irq(self, event, data):
        if event == _IRQ_SCAN_RESULT:
            try:
                frame = extract_secure_frame_from_adv(data[4])
            except Exception:
                return
            if not frame:
                return

            parsed = parse_frame(frame)
            if not parsed:
                return

            unique_id, msgid, ttl, typ, ciphertext, ttl_type = parsed
            if typ not in (TYPE_COUNT, TYPE_HEATMAP):
                return

            key = bytes(unique_id) + int(msgid).to_bytes(2, "big")
            if self._seen_check_add(key):
                return

            plaintext = decrypt_data(ciphertext, unique_id, msgid, ttl_type)
            packed_room = plaintext[:2]
            is_west, block_num, level, room_num = unpack_classroom_id(packed_room)

            if str(block_num) != BUILDING_PREFIX:
                return

            if typ == TYPE_COUNT:
                value = int.from_bytes(plaintext[2:4], "big")
            else:
                value = plaintext[2]

            room_id = classroom_fields_to_room_id(is_west, block_num, level, room_num)
            self._rx_buf.append((typ, room_id, value))

        elif event == _IRQ_SCAN_DONE:
            self.ble.gap_scan(SCAN_MS, 30000, 30000)

    def _publish(self, room_id, count):
        topic = "csc2106/{}/classroom/{}/occupancy".format(PRIMARY_ID, room_id)
        msg = ujson.dumps({"room_id": room_id, "count": count, "timestamp": time.time()})
        led.on()
        try:
            self.client.publish(topic.encode(), encrypt_payload(msg), qos=1)
            print("[{}] (ACTIVE) → {} count={}".format(NODE_ID, room_id, count))
        except OSError as e:
            print("[{}] MQTT publish failed:".format(NODE_ID), e)
            raise
        finally:
            led.off()

    def _publish_heatmap(self, room_id, packed):
        z1 = (packed >> 6) & 0x3
        z2 = (packed >> 4) & 0x3
        z3 = (packed >> 2) & 0x3
        z4 = packed & 0x3

        topic = "csc2106/{}/classroom/{}/heatmap".format(PRIMARY_ID, room_id)
        msg = ujson.dumps({"room_id": room_id, "zones": [z1, z2, z3, z4], "timestamp": time.time()})
        led.on()
        try:
            self.client.publish(topic.encode(), encrypt_payload(msg), qos=1)
            print("[{}] (ACTIVE) HMAP → {} zones=[{},{},{},{}]".format(NODE_ID, room_id, z1, z2, z3, z4))
        except OSError as e:
            print("[{}] MQTT heatmap publish failed:".format(NODE_ID), e)
            raise
        finally:
            led.off()

    def run(self):
        last_ping = time.ticks_ms()
        while True:
            if time.ticks_diff(time.ticks_ms(), last_ping) >= 30_000:
                try:
                    self.client.ping()
                except OSError:
                    pass
                last_ping = time.ticks_ms()

            if self.is_active:
                while self._rx_buf:
                    typ, room_id, value = self._rx_buf.pop(0)
                    try:
                        if typ == TYPE_COUNT:
                            self._publish(room_id, value)
                        elif typ == TYPE_HEATMAP:
                            self._publish_heatmap(room_id, value)
                    except OSError:
                        print("[{}] MQTT error, reconnecting...".format(NODE_ID))
                        time.sleep(5)
                        try:
                            self.client = mqtt_connect(self.on_mqtt_msg)
                        except Exception:
                            pass
            else:
                self._rx_buf.clear()

            try:
                self.client.check_msg()
            except OSError:
                print("[{}] MQTT keepalive error, reconnecting...".format(NODE_ID))
                time.sleep(5)
                try:
                    self.client = mqtt_connect(self.on_mqtt_msg)
                except Exception:
                    pass

            time.sleep_ms(10)

connect_wifi()
led = Pin("LED", Pin.OUT)
node = BackupHeadNode()
node.client = mqtt_connect(node.on_mqtt_msg)
node.run()
