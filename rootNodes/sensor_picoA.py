# sensor_picoA.py  –  Sensor Pico, Building A
# Collects occupancy data and delivers it to the active head node via MQTT.
#
# Failover state machine (no coordination with head nodes needed):
#
#   send to active_inbox
#   ├── ACK received  →  done ✓
#   └── no ACK (after MAX_RETRIES)
#       └── probe standby_inbox
#           ├── ACK received  →  SWAP active↔standby, done ✓
#           └── no ACK        →  both head nodes down, skip this cycle

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
ROOM_ID       = "E2-02-01"
ROOM_NAME     = "E2-02-01"
CLIENT_ID     = b"SensorA"

# Head node inboxes for this building
INBOX_A   = "csc2106/classroom/" + ROOM_ID + "/HeadNode-E2/data"
INBOX_B   = "csc2106/classroom/" + ROOM_ID + "/BackUp-E2/data"
ACK_TOPIC = "csc2106/classroom/" + ROOM_ID + "/ack"

PUBLISH_INTERVAL_MS = 15000   # how often to collect + send a reading
ACK_TIMEOUT_MS      = 2000    # how long to wait for an ACK per attempt
MAX_RETRIES         = 2       # retries to active before probing standby
                               # worst-case wait = (MAX_RETRIES+1)*ACK_TIMEOUT_MS
                               #                 = 3 * 2s = 6s  (well within 15s)

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
MAX_CAPACITY = 30
sim_count    = 0

def read_sensor():
    """Replace this body with real sensor logic when hardware is ready."""
    global sim_count
    delta = (urandom.getrandbits(3) % 7) - 3
    sim_count = max(0, min(MAX_CAPACITY, sim_count + delta))
    return sim_count

# ── Failover state ─────────────────────────────────────────────────────────────
active_inbox  = INBOX_A   # starts with headA as active
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
    print("[SensorA] MQTT connected, active head=" + active_inbox)
    return c

client = mqtt_connect()

# ── ACK wait (polls check_msg until ACK arrives or timeout) ───────────────────
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

# ── Send to one inbox and wait for ACK ─────────────────────────────────────────
def send_once(inbox, payload):
    try:
        client.publish(inbox.encode(), payload, qos=1)
        return wait_for_ack()
    except OSError:
        return False

# ── Deliver with retry + failover ──────────────────────────────────────────────
def deliver(payload):
    """
    Tries active_inbox up to (MAX_RETRIES+1) times.
    On failure probes standby_inbox once.
    Swaps active↔standby if standby ACKs.
    Returns True if data was delivered to either head node.
    """
    global active_inbox, standby_inbox

    # ── Try active ─────────────────────────────────────────────────────────────
    for attempt in range(MAX_RETRIES + 1):
        if send_once(active_inbox, payload):
            return True
        print("[SensorA] No ACK from active (attempt " + str(attempt + 1) + ")")

    # ── Active exhausted — probe standby ───────────────────────────────────────
    print("[SensorA] Active unresponsive — probing standby: " + standby_inbox)
    if send_once(standby_inbox, payload):
        active_inbox, standby_inbox = standby_inbox, active_inbox
        print("[SensorA] SWAPPED — new active: " + active_inbox)
        return True

    # ── Both down ──────────────────────────────────────────────────────────────
    print("[SensorA] Both head nodes unresponsive — data dropped this cycle")
    return False

# ── Main loop ──────────────────────────────────────────────────────────────────
last_pub = time.ticks_ms() - PUBLISH_INTERVAL_MS   # publish immediately on start

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
            print("[SensorA] delivered  count=" + str(count)
                  + "  via=" + active_inbox.split("/")[3])
        last_pub = time.ticks_ms()   # reset after (potentially slow) delivery

    # Keep MQTT alive between publishes
    try:
        client.check_msg()
    except OSError:
        print("[SensorA] MQTT error, reconnecting...")
        time.sleep(5)
        try:
            client = mqtt_connect()
        except Exception:
            pass

    time.sleep_ms(100)
