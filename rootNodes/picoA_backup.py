# picoA_backup.py  –  Head Node (Backup), Building E2
#
# Selective Flooding implementation:
#   - Stays SILENT while primary (HeadNode-E2) is online
#   - Monitors primary's status topic via MQTT
#   - Activates and forwards BLE data to broker ONLY when primary goes offline
#   - Returns to standby automatically when primary comes back online
#
# Selective forward path:
#   ACTIVE:  BLE scan → parse → MQTT publish (under primary's topic)
#   STANDBY: BLE scan → parse → discard (do not publish)

import bluetooth
import time
import ujson
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
NODE_ID       = "BackUp-E2"
PRIMARY_ID    = "HeadNode-E2"
CLIENT_ID     = ("Pi4-" + NODE_ID).encode()

STATUS_TOPIC         = "csc2106/{}/status".format(NODE_ID)
PRIMARY_STATUS_TOPIC = "csc2106/{}/status".format(PRIMARY_ID)

SCAN_MS  = 10_000
SEEN_MAX = 300

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
def mqtt_connect(on_msg_cb):
    c = simple.MQTTClient(client_id=CLIENT_ID, server=BROKER_IP, keepalive=60)
    c.set_last_will(STATUS_TOPIC.encode(), b"offline", retain=True, qos=1)
    c.set_callback(on_msg_cb)
    c.connect()
    c.publish(STATUS_TOPIC.encode(), b"online", retain=True, qos=1)
    c.subscribe(PRIMARY_STATUS_TOPIC.encode(), qos=1)
    print("[{}] MQTT connected — broker {}".format(NODE_ID, BROKER_IP))
    print("[{}] Monitoring primary status: {}".format(NODE_ID, PRIMARY_STATUS_TOPIC))
    return c

# ── BLE frame helpers ─────────────────────────────────────────────────────────
def decode_room_id(code):
    # Sensor Picos send a 3-char room code to fit within the 25-char BLE frame.
    # "201" → "E2-02-01",  "603" → "E6-02-03"
    return "E{}-02-{}".format(code[0], code[1:])

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

# ── Backup Head Node ──────────────────────────────────────────────────────────
class BackupHeadNode:
    def __init__(self):
        self.client    = None
        self.seen      = []
        self._rx_buf   = []
        self.is_active = False   # STANDBY by default — selective flooding

        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)
        self.ble.gap_scan(SCAN_MS, 30000, 30000)
        print("[{}] BLE scanning (STANDBY — waiting for primary to fail)".format(NODE_ID))

    # ── Selective flooding control ─────────────────────────────────────────────
    def on_mqtt_msg(self, topic, msg):
        """Activate or deactivate based on primary's health status."""
        if topic.decode() != PRIMARY_STATUS_TOPIC:
            return
        status = msg.decode()
        if status == "offline" and not self.is_active:
            self.is_active = True
            print("[{}] Primary OFFLINE — activating, now forwarding BLE data".format(NODE_ID))
        elif status == "online" and self.is_active:
            self.is_active = False
            self._rx_buf.clear()   # discard any queued frames
            print("[{}] Primary ONLINE — returning to standby".format(NODE_ID))

    # ── Dedup cache ───────────────────────────────────────────────────────────
    def _seen_check_add(self, key):
        if key in self.seen:
            return True
        self.seen.append(key)
        if len(self.seen) > SEEN_MAX:
            del self.seen[0: len(self.seen) - SEEN_MAX]
        return False

    # ── BLE IRQ ───────────────────────────────────────────────────────────────
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
            if typ != "C":
                return

            key = "{}:{}".format(orig, msgid)
            if self._seen_check_add(key):
                return

            self._rx_buf.append(payload)

        elif event == _IRQ_SCAN_DONE:
            self.ble.gap_scan(SCAN_MS, 30000, 30000)

    # ── MQTT publish ──────────────────────────────────────────────────────────
    def _publish(self, data_field):
        # data_field format: "201:5"  (3-char room code + count)
        try:
            room_code, count_str = data_field.split(":", 1)
            room_id = decode_room_id(room_code)   # "201" → "E2-02-01"
            count   = int(count_str)
        except Exception:
            print("[{}] bad data field: {}".format(NODE_ID, data_field))
            return

        # Publish under primary's topic so the bridge picks it up seamlessly
        # without any changes when failover occurs
        topic = "csc2106/{}/classroom/{}/occupancy".format(PRIMARY_ID, room_id)
        msg   = ujson.dumps({
            "room_id":   room_id,
            "count":     count,
            "occupied":  count > 0,
            "timestamp": time.time(),
        })
        led.on()
        try:
            self.client.publish(topic.encode(), msg.encode(), qos=1)
            print("[{}] (ACTIVE) → {} count={}".format(NODE_ID, room_id, count))
        except OSError as e:
            print("[{}] MQTT publish failed:".format(NODE_ID), e)
            raise
        finally:
            led.off()

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self):
        last_ping = time.ticks_ms()
        while True:
            # Send keepalive ping every 30s to prevent broker timeout
            if time.ticks_diff(time.ticks_ms(), last_ping) >= 30_000:
                try:
                    self.client.ping()
                except OSError:
                    pass
                last_ping = time.ticks_ms()

            if self.is_active:
                # Forward queued BLE frames to broker
                while self._rx_buf:
                    payload = self._rx_buf.pop(0)
                    try:
                        self._publish(payload)
                    except OSError:
                        print("[{}] MQTT error, reconnecting...".format(NODE_ID))
                        time.sleep(5)
                        try:
                            self.client = mqtt_connect(self.on_mqtt_msg)
                        except Exception:
                            pass
            else:
                # Standby: discard BLE frames silently
                self._rx_buf.clear()

            # check_msg triggers on_mqtt_msg when primary status changes
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

# ── Boot ──────────────────────────────────────────────────────────────────────
connect_wifi(WIFI_SSID, WIFI_PASSWORD)
led  = Pin("LED", Pin.OUT)

node        = BackupHeadNode()
node.client = mqtt_connect(node.on_mqtt_msg)

node.run()
