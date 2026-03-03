from machine import Pin, time_pulse_us
import time

# ----------------------
# Pin Setup
# ----------------------
TRIG1 = Pin(3, Pin.OUT)
ECHO1 = Pin(2, Pin.IN)

TRIG2 = Pin(5, Pin.OUT)
ECHO2 = Pin(4, Pin.IN)

THRESHOLD = 125          # Lower threshold to avoid wall detection
TIMEOUT_WINDOW = 1.5      # Seconds to wait for second trigger
MIN_INTERVAL = 1.5      # Minimum time between counts

state = "IDLE"
state_time = 0
last_trigger_time = 0
count = 0
s1_hits = 0
s2_hits = 0


# ----------------------
# Ultrasonic Function
# ----------------------
def get_distance(trig, echo):
    trig.low()
    time.sleep_us(2)

    trig.high()
    time.sleep_us(10)
    trig.low()

    try:
        duration = time_pulse_us(echo, 1, 30000)
    except OSError:
        return 999  # timeout → treat as far away

    distance = (duration / 2) * 0.0343

    # Filter unrealistic values
    if distance <= 0 or distance > 400:
        return 999

    return distance


# ----------------------
# Main Loop
# ----------------------
while True:
    # Trigger sensors one at a time (prevents crosstalk)
    d1 = get_distance(TRIG1, ECHO1)
    time.sleep_ms(60)
    d2 = get_distance(TRIG2, ECHO2)

    now = time.time()
    
    #print("D1: {:.1f} cm | D2: {:.1f} cm | State: {}".format(d1, d2, state))

    # Debug (optional)
    # print("D1:", d1, "D2:", d2, "State:", state)

    # ----------------------
    # IDLE STATE
    # ----------------------
    if state == "IDLE":
        if d1 < THRESHOLD:
            s1_hits += 1
        else:
            s1_hits = 0

        if d2 < THRESHOLD:
            s2_hits += 1
        else:
            s2_hits = 0

        if s1_hits >= 2:
            state = "S1_TRIGGERED"
            state_time = now
            s1_hits = 0

        elif s2_hits >= 2:
            state = "S2_TRIGGERED"
            state_time = now
            s2_hits = 0

    # ----------------------
    # S1 FIRST → ENTER
    # ----------------------
    elif state == "S1_TRIGGERED":
        if d2 < THRESHOLD and (now - last_trigger_time) > MIN_INTERVAL:
            count += 1
            print("ENTER → Count:", count)
            last_trigger_time = now
            state = "WAIT_CLEAR"

        elif now - state_time > TIMEOUT_WINDOW:
            state = "IDLE"

    # ----------------------
    # S2 FIRST → EXIT
    # ----------------------
    elif state == "S2_TRIGGERED":
        if d1 < THRESHOLD and (now - last_trigger_time) > MIN_INTERVAL:
            if count > 0:
                count -= 1
            print("EXIT → Count:", count)
            last_trigger_time = now
            state = "WAIT_CLEAR"

        elif now - state_time > TIMEOUT_WINDOW:
            state = "IDLE"

    # ----------------------
    # WAIT UNTIL BOTH CLEAR
    # ----------------------
    elif state == "WAIT_CLEAR":
        if d1 > THRESHOLD and d2 > THRESHOLD:
            state = "IDLE"

    time.sleep_ms(20)