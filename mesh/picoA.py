import umqtt.simple as simple
from machine import Pin
import time
import network


def connect_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(ssid, password)
        while not wlan.isconnected():
            time.sleep(1)

    print("WiFi connected:", wlan.ifconfig())

connect_wifi("Wireless@Home", "63841520")


btn_toggle = Pin(21, Pin.IN, Pin.PULL_UP)
btn_hello  = Pin(22, Pin.IN, Pin.PULL_UP)
led = Pin(20, Pin.OUT)

prev_toggle = btn_toggle.value()
prev_hello  = btn_hello.value()

def callback_function(topic,msg):
    if msg == b"TOGGLE":
        led.toggle()


client = simple.MQTTClient(
    client_id=b"PicoA",
    server="192.168.1.28",
    keepalive=30
)

client.set_last_will(
    b"csc2106/devA/status",
    b"offline",
    retain=True,
    qos=1
)

client.set_callback(callback_function)
client.connect()

# Publish online status
client.publish(
    b"csc2106/devA/status",
    b"online",
    retain=True,
    qos=1
)

client.subscribe(b"csc2106/nodeA/led/cmd",1)

print("MQTT connected")


while True:

    cur_toggle = btn_toggle.value()
    cur_hello  = btn_hello.value()
    client.check_msg()

    if prev_toggle == 1 and cur_toggle == 0:
        print("TOGGLE pressed")
        client.publish(
            b"csc2106/nodeB/led/cmd",
            b"TOGGLE",
            qos=1
        )


    if prev_hello == 1 and cur_hello == 0:
        print("HELLO pressed")
        client.publish(
            b"csc2106/led/hello",
            b"HELLO",
            qos=1
        )

    prev_toggle = cur_toggle
    prev_hello  = cur_hello

    time.sleep(0.05) 
