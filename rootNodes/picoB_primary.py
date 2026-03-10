# Head Node A  –  Building B
# Identical logic to picoA_primary.py. Only ROOM_ID differs.

import umqtt.simple as simple
from machine import Pin
import time
import network

# ── Config ─────────────────────────────────────────────────────────────────────
WIFI_SSID = "js"
WIFI_PASSWORD = "12345678"
BROKER_IP = "172.20.10.2"
ROOM_ID = "E6-02-02"  # <── Building B
NODE_ID = "HeadNode-E6"

INBOX_TOPIC = "csc2106/" + NODE_ID + "/classroom/" + ROOM_ID + "/data"
OCCUPANCY_TOPIC = "csc2106/" + NODE_ID + "/classroom/" + ROOM_ID + "/occupancy"
ACK_TOPIC = "csc2106/" + NODE_ID + "/classroom/" + ROOM_ID + "/ack"
STATUS_TOPIC = "csc2106/" + NODE_ID + "/classroom/" + ROOM_ID + "/status"


# ── WiFi ───────────────────────────────────────────────────────────────────────
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


connect_wifi(WIFI_SSID, WIFI_PASSWORD)

led = Pin("LED", Pin.OUT)


# ── MQTT callback ──────────────────────────────────────────────────────────────
def on_message(topic, msg):
    if topic.decode() != INBOX_TOPIC:
        return
    try:
        led.on()
        client.publish(OCCUPANCY_TOPIC.encode(), msg, qos=1)
        client.publish(ACK_TOPIC.encode(), NODE_ID.encode(), qos=1)
        print("[" + NODE_ID + "] forwarded + ACKed  " + str(len(msg)) + "B")
    except Exception as e:
        print("[" + NODE_ID + "] publish FAILED — no ACK sent:", e)
    finally:
        led.off()


# ── MQTT connect ───────────────────────────────────────────────────────────────
def mqtt_connect():
    c = simple.MQTTClient(
        client_id=("Pi4-" + NODE_ID).encode(),
        server=BROKER_IP,
        keepalive=60,
    )
    c.set_last_will(STATUS_TOPIC.encode(), b"offline", retain=True, qos=1)
    c.set_callback(on_message)
    c.connect()
    c.publish(STATUS_TOPIC.encode(), b"online", retain=True, qos=1)
    c.subscribe(INBOX_TOPIC.encode(), qos=1)
    print("[" + NODE_ID + "] ready — inbox: " + INBOX_TOPIC)
    return c


client = mqtt_connect()

# ── Main loop ──────────────────────────────────────────────────────────────────
while True:
    try:
        client.wait_msg()
    except OSError:
        print("[" + NODE_ID + "] MQTT error, reconnecting...")
        time.sleep(5)
        try:
            client = mqtt_connect()
        except Exception:
            pass
