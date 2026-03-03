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

led = Pin(20, Pin.OUT)
btn_toggle = Pin(21, Pin.IN, Pin.PULL_UP)
prev_toggle = btn_toggle.value()

def callback_function(topic,msg):
    client.publish(b"csc2106/led/ack", b"ACK",False,1)
    if msg == b"TOGGLE":
        led.toggle()

client = simple.MQTTClient(
    client_id=b"PicoB",
    server="10.236.91.21",
    keepalive=0
)
client.set_last_will(
    b"csc2106/devB/status",
    b"offline",
    retain=True,
    qos=1
)

client.set_callback(callback_function)
client.connect()

client.publish(b"csc2106/devB/status",b"online",True,1)

client.subscribe(b"csc2106/nodeB/led/cmd",1)


while True:

    cur_toggle = btn_toggle.value()
    client.check_msg()


    if prev_toggle == 1 and cur_toggle == 0:
        print("TOGGLE pressed")
        client.publish(
            b"csc2106/nodeA/led/cmd",
            b"TOGGLE",
            qos=1
        )
    prev_toggle = cur_toggle
    time.sleep(0.05)  