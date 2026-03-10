# sensor_picoB.py  –  Sensor Pico, Building B
# Identical logic to sensor_picoA.py. Only room config differs.

import umqtt.simple as simple
from machine import Pin
import time
import network
import urandom
import ujson

# ── Config ─────────────────────────────────────────────────────────────────────
WIFI_SSID     = "js"
WIFI_PASSWORD = "12345678"
BROKER_IP     = "172.20.10.2"
ROOM_ID       = "E6-02-02"
ROOM_NAME     = "E6-02-02"
CLIENT_ID     = b"SensorB"

INBOX_A   = "csc2106/classroom/" + ROOM_ID + "/HeadNode-E6/data"
INBOX_B   = "csc2106/classroom/" + ROOM_ID + "/Backup-E6/data"
ACK_TOPIC = "csc2106/classroom/" + ROOM_ID + "/ack"

PUBLISH_INTERVAL_MS = 15000
ACK_TIMEOUT_MS      = 2000
MAX_RETRIES         = 2

# ── WiFi ───────────────────────────────────────────────────────────────────────
def connect_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(ssid, password)
        while not wlan.isconnected():
            time.sleep(1)
    print("WiFi connected:", wlan.ifconfig())

connect_wifi(WIFI_SSID, WIFI_PASSWORD)

led = Pin("LED", Pin.OUT)

# ── Simulated occupancy (replace with real sensor read) ────────────────────────
MAX_CAPACITY = 40
sim_count    = 5   # Room B starts with a small crowd

def read_sensor():
    """Replace this body with real sensor logic when hardware is ready."""
    global sim_count
    delta = (urandom.getrandbits(4) % 9) - 4
    sim_count = max(0, min(MAX_CAPACITY, sim_count + delta))
    return sim_count

# ── Failover state ─────────────────────────────────────────────────────────────
active_inbox  = INBOX_A
standby_inbox = INBOX_B

# ── ACK tracking ───────────────────────────────────────────────────────────────
_ack_received = False

def on_message(topic, msg):
    global _ack_received
    if topic.decode() == ACK_TOPIC:
        _ack_received = True

# ── MQTT connect helper ────────────────────────────────────────────────────────
def mqtt_connect():
    c = simple.MQTTClient(client_id=CLIENT_ID, server=BROKER_IP, keepalive=60)
    c.set_callback(on_message)
    c.connect()
    c.subscribe(ACK_TOPIC.encode(), qos=1)
    print("[E6-Building] MQTT connected, active head=" + active_inbox)
    return c

client = mqtt_connect()

# ── ACK wait ───────────────────────────────────────────────────────────────────
def wait_for_ack():
    global _ack_received
    _ack_received = False
    deadline = time.ticks_add(time.ticks_ms(), ACK_TIMEOUT_MS)
    while not _ack_received:
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            return False
        try:
            client.check_msg()
        except OSError:
            return False
        time.sleep_ms(50)
    return True

def send_once(inbox, payload):
    try:
        client.publish(inbox.encode(), payload, qos=1)
        return wait_for_ack()
    except OSError:
        return False

# ── Deliver with retry + failover ──────────────────────────────────────────────
def deliver(payload):
    global active_inbox, standby_inbox

    for attempt in range(MAX_RETRIES + 1):
        if send_once(active_inbox, payload):
            return True
        print("[SensorB] No ACK from active (attempt " + str(attempt + 1) + ")")

    print("[SensorB] Active unresponsive — probing standby: " + standby_inbox)
    if send_once(standby_inbox, payload):
        active_inbox, standby_inbox = standby_inbox, active_inbox
        print("[SensorB] SWAPPED — new active: " + active_inbox)
        return True

    print("[SensorB] Both head nodes unresponsive — data dropped this cycle")
    return False

# ── Main loop ──────────────────────────────────────────────────────────────────
last_pub = time.ticks_ms() - PUBLISH_INTERVAL_MS

while True:
    now = time.ticks_ms()

    if time.ticks_diff(now, last_pub) >= PUBLISH_INTERVAL_MS:
        count = read_sensor()
        payload = ujson.dumps({
            "room_id":   ROOM_ID,
            "room_name": ROOM_NAME,
            "occupied":  count > 0,
            "count":     count,
            "timestamp": time.time(),
        })
        led.on()
        ok = deliver(payload.encode())
        led.off()
        if ok:
            print("[SensorB] delivered  count=" + str(count)
                  + "  via=" + active_inbox.split("/")[3])
        last_pub = time.ticks_ms()

    try:
        client.check_msg()
    except OSError:
        print("[SensorB] MQTT error, reconnecting...")
        time.sleep(5)
        try:
            client = mqtt_connect()
        except Exception:
            pass

    time.sleep_ms(100)
