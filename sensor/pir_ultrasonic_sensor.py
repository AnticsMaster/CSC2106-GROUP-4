from machine import Pin, time_pulse_us
import time

# ============================================================
# Configuration
# ============================================================

# PIR
PIR_PIN = 26
PIR_WARMUP_MS = 2000

# Debounce PIR (ignore rapid toggles / noise)
PIR_DEBOUNCE_MS = 200
# End the ultrasonic session when PIR has been quiet this long
PIR_QUIET_TIMEOUT_MS = 1500

# Low power behaviour when idle
IDLE_SLEEP_MS = 200          # how long we sleep per idle loop
USE_LIGHTSLEEP = True        # set False if your board/port doesn't support lightsleep well

# Ultrasonics
TRIG1_PIN = 3
ECHO1_PIN = 2
TRIG2_PIN = 5
ECHO2_PIN = 4

THRESHOLD_CM = 125           # detection threshold (tune to your setup)
MAX_RANGE_CM = 400           # sanity filter

# Reduce false triggers from noisy ultrasonic readings
HIT_CONFIRM = 2              # require N consecutive hits to consider "triggered"

# Timing for the directional FSM
TIMEOUT_WINDOW_MS = 1500     # max time between first sensor trigger and second
MIN_INTERVAL_MS = 1500       # cooldown between counts to prevent double counts

# Crosstalk avoidance
INTER_SENSOR_DELAY_MS = 60   # delay between firing sensor 1 and sensor 2
LOOP_DELAY_MS = 20           # short delay at end of each FSM step


# ============================================================
# Hardware Setup
# ============================================================

pir = Pin(PIR_PIN, Pin.IN)

TRIG1 = Pin(TRIG1_PIN, Pin.OUT)
ECHO1 = Pin(ECHO1_PIN, Pin.IN)

TRIG2 = Pin(TRIG2_PIN, Pin.OUT)
ECHO2 = Pin(ECHO2_PIN, Pin.IN)


# ============================================================
# Utilities (ticks-based timing)
# ============================================================

def now_ms():
    return time.ticks_ms()

def elapsed_ms(t0):
    return time.ticks_diff(now_ms(), t0)

def sleep_ms(ms):
    # Low-power friendly sleep
    if USE_LIGHTSLEEP and hasattr(time, "sleep_ms"):
        # time.sleep_ms already yields well; lightsleep is in machine, not time
        pass
    time.sleep_ms(ms)

def idle_sleep(ms):
    # Try to use machine.lightsleep if available (lower power), else fallback.
    if USE_LIGHTSLEEP:
        try:
            import machine
            machine.lightsleep(ms)
            return
        except Exception:
            pass
    time.sleep_ms(ms)


# ============================================================
# Ultrasonic Distance
# ============================================================

def get_distance_cm(trig: Pin, echo: Pin) -> int:
    """
    Returns distance in cm as an int.
    Returns a large number (999) on timeout / invalid.
    """
    trig.low()
    time.sleep_us(2)

    trig.high()
    time.sleep_us(10)
    trig.low()

    try:
        dur = time_pulse_us(echo, 1, 30000)  # 30 ms timeout
    except OSError:
        return 999

    # Convert to cm:
    # sound speed ~343 m/s = 0.0343 cm/us
    # distance = (dur/2) * 0.0343
    # Use integer-ish math to reduce float cost:
    # (dur * 343) / 20000  => close to (dur/2)*0.0343
    dist = (dur * 343) // 20000

    if dist <= 0 or dist > MAX_RANGE_CM:
        return 999

    return int(dist)


# ============================================================
# Direction / Counting FSM
# ============================================================

IDLE = 0
S1_TRIGGERED = 1
S2_TRIGGERED = 2
WAIT_CLEAR = 3

state = IDLE
state_start_ms = 0
last_count_ms = 0

count = 0

# hit counters (false-trigger reduction)
s1_hits = 0
s2_hits = 0

def reset_ultra_fsm(t_ms: int):
    global state, state_start_ms, s1_hits, s2_hits
    state = IDLE
    state_start_ms = t_ms
    s1_hits = 0
    s2_hits = 0

def ultrasonic_step(t_ms: int):
    """
    Runs one step of ultrasonic FSM while session is active.
    """
    global state, state_start_ms, last_count_ms, count, s1_hits, s2_hits

    d1 = get_distance_cm(TRIG1, ECHO1)
    time.sleep_ms(INTER_SENSOR_DELAY_MS)
    d2 = get_distance_cm(TRIG2, ECHO2)

    # ----------------------
    # FSM
    # ----------------------
    if state == IDLE:
        # hit confirmation logic
        if d1 < THRESHOLD_CM:
            s1_hits += 1
        else:
            s1_hits = 0

        if d2 < THRESHOLD_CM:
            s2_hits += 1
        else:
            s2_hits = 0

        if s1_hits >= HIT_CONFIRM:
            state = S1_TRIGGERED
            state_start_ms = t_ms
            s1_hits = 0
            s2_hits = 0

        elif s2_hits >= HIT_CONFIRM:
            state = S2_TRIGGERED
            state_start_ms = t_ms
            s1_hits = 0
            s2_hits = 0

    elif state == S1_TRIGGERED:
        # Wait for sensor 2 within timeout window -> ENTER
        if d2 < THRESHOLD_CM and time.ticks_diff(t_ms, last_count_ms) > MIN_INTERVAL_MS:
            count += 1
            print("ENTER → Count:", count)
            last_count_ms = t_ms
            state = WAIT_CLEAR

        elif time.ticks_diff(t_ms, state_start_ms) > TIMEOUT_WINDOW_MS:
            state = IDLE

    elif state == S2_TRIGGERED:
        # Wait for sensor 1 within timeout window -> EXIT
        if d1 < THRESHOLD_CM and time.ticks_diff(t_ms, last_count_ms) > MIN_INTERVAL_MS:
            if count > 0:
                count -= 1
            print("EXIT → Count:", count)
            last_count_ms = t_ms
            state = WAIT_CLEAR

        elif time.ticks_diff(t_ms, state_start_ms) > TIMEOUT_WINDOW_MS:
            state = IDLE

    elif state == WAIT_CLEAR:
        # Avoid immediate retriggering: require both to clear
        if d1 > THRESHOLD_CM and d2 > THRESHOLD_CM:
            state = IDLE

    time.sleep_ms(LOOP_DELAY_MS)


# ============================================================
# PIR session gating (low power + false trigger reduction)
# ============================================================

pir_motion_flag = False
last_pir_irq_ms = 0
last_pir_high_ms = 0

def pir_irq_handler(pin):
    """
    Rising-edge IRQ handler: sets a flag (debounced).
    Keep it super short (no prints, no allocations).
    """
    global pir_motion_flag, last_pir_irq_ms
    t = time.ticks_ms()
    if time.ticks_diff(t, last_pir_irq_ms) > PIR_DEBOUNCE_MS:
        pir_motion_flag = True
        last_pir_irq_ms = t

# Use interrupt if available (reduces polling & helps low power)
try:
    pir.irq(trigger=Pin.IRQ_RISING, handler=pir_irq_handler)
except Exception:
    # If IRQ not supported on your port, we'll just poll.
    pass


# ============================================================
# Main Loop
# ============================================================

print("Warming up PIR...")
time.sleep_ms(PIR_WARMUP_MS)
print("Ready")

session_active = False
reset_ultra_fsm(now_ms())

while True:
    t = now_ms()

    # --- Determine motion "activity" ---
    # Primary: interrupt flag (if IRQ is set)
    # Fallback: poll PIR
    pir_val = pir.value()
    if pir_val == 1:
        last_pir_high_ms = t

    if pir_motion_flag:
        pir_motion_flag = False
        last_pir_high_ms = t  # treat as recent motion

    # --- Start session on motion ---
    if not session_active and (time.ticks_diff(t, last_pir_high_ms) <= PIR_DEBOUNCE_MS or pir_val == 1):
        session_active = True
        print("\nMotion detected → Ultrasonic counting ON")
        reset_ultra_fsm(t)

    # --- While active, run ultrasonic FSM ---
    if session_active:
        ultrasonic_step(t)

        # End session if PIR quiet for long enough
        if time.ticks_diff(t, last_pir_high_ms) > PIR_QUIET_TIMEOUT_MS:
            session_active = False
            print("No motion → Ultrasonic counting OFF\n")
            reset_ultra_fsm(t)

    # --- Idle: go low power ---
    else:
        # If PIR is noisy, polling too fast causes false wakeups.
        # Slow idle loop + IRQ helps a lot.
        idle_sleep(IDLE_SLEEP_MS)