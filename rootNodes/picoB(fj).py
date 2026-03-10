import umqtt.simple as simple
from machine import Pin
import time
import network
import urandom
import ujson


# ── Config ─────────────────────────────────────────────────────────────────────
WIFI_SSID = "js"
WIFI_PASSWORD = "12345678"
BROKER_IP = "172.20.10.2"
ROOM_ID = "room-B"
ROOM_NAME = "E6-02-01"
PUBLISH_TOPIC = "csc2106/classroom/" + ROOM_ID + "/occupancy"
STATUS_TOPIC = "csc2106/classroom/" + ROOM_ID + "/status"
PUBLISH_INTERVAL_MS = 15000  # publish every 15 seconds


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


# ── Hardware ───────────────────────────────────────────────────────────────────
led = Pin("LED", Pin.OUT)  # onboard LED blinks on each publish


# ── Simulated occupancy ───────────────────────────────────────────────────────
# Room B starts with a small crowd and has a higher capacity for variety.
MAX_CAPACITY = 40
sim_count = 5


def next_count(current):
    """Random-walk: delta in [-4, +4], clamped to [0, MAX_CAPACITY]."""
    delta = (urandom.getrandbits(4) % 9) - 4  # 0-8 then shift → -4..+4
    n = current + delta
    if n < 0:
        n = 0
    if n > MAX_CAPACITY:
        n = MAX_CAPACITY
    return n


# ── MQTT ───────────────────────────────────────────────────────────────────────
client = simple.MQTTClient(client_id=b"PicoB", server=BROKER_IP, keepalive=60)

client.set_last_will(STATUS_TOPIC.encode(), b"offline", retain=True, qos=1)

client.connect()
client.publish(STATUS_TOPIC.encode(), b"online", retain=True, qos=1)

print("[PicoB] MQTT connected, publishing to " + PUBLISH_TOPIC)


# ── Main loop ──────────────────────────────────────────────────────────────────
last_pub = time.ticks_ms() - PUBLISH_INTERVAL_MS  # first publish immediately

while True:
    now = time.ticks_ms()

    if time.ticks_diff(now, last_pub) >= PUBLISH_INTERVAL_MS:
        sim_count = next_count(sim_count)

        payload = ujson.dumps(
            {
                "room_id": ROOM_ID,
                "room_name": ROOM_NAME,
                "occupied": sim_count > 0,
                "count": sim_count,
                "timestamp": time.time(),
            }
        )

        led.on()
        client.publish(PUBLISH_TOPIC.encode(), payload.encode(), qos=1)
        led.off()

        print("[PicoB] count=" + str(sim_count))
        last_pub = now

    # Service incoming MQTT traffic / keepalive
    try:
        client.check_msg()
    except OSError:
        print("[PicoB] MQTT error, reconnecting...")
        time.sleep(5)
        try:
            client.connect()
            client.publish(STATUS_TOPIC.encode(), b"online", retain=True, qos=1)
        except Exception:
            pass

    time.sleep_ms(100)
