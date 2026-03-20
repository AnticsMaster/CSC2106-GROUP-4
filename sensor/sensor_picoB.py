# sensor_picoB.py  –  Sensor Pico, Building E6
#
# Triple role:
#   1. Door PIR + 2× ultrasonic for entrance/exit counting
#   2. 4× heatmap PIRs (one per zone) for classroom activity heatmap
#   3. BLE mesh relay — forwards other classrooms' frames toward the head node
#
# Topology (E6 building):
#   Classroom 3 → Classroom 2 → Classroom 1 → Head Node
#
# Each classroom Pico scans BLE continuously and relays frames it hasn't seen
# before (TTL-1). On count change it injects its own "C" frame into the mesh.
# No WiFi or MQTT on sensor Picos — BLE only.

import bluetooth
import time
import ubinascii
import machine
from machine import Pin, time_pulse_us
import urandom
from micropython import const

# ── BLE IRQ events ────────────────────────────────────────────────────────────
_IRQ_SCAN_RESULT = const(5)
_IRQ_SCAN_DONE   = const(6)

# ── BLE config ────────────────────────────────────────────────────────────────
ADV_INTERVAL_US = 200_000   # advertising interval during burst
ADV_BURST_MS    = 300       # advertise for 300 ms then stop
SCAN_MS         = 10_000    # scan window (restarts automatically)
DEFAULT_TTL     = 3         # enough for 3-hop chain (CL3→CL2→CL1→Head)
SEEN_MAX        = 200       # dedup cache size

# ── Node identity ─────────────────────────────────────────────────────────────
# NODE_ID is stable across reboots — derived from hardware UID.
# Print this on first boot and give it to your teammate to add to NODE_MAP
# in the head node files.
NODE_ID = ubinascii.hexlify(machine.unique_id()).decode()[-6:]

# ── Classroom identity ────────────────────────────────────────────────────────
# Change ROOM_ID for each classroom Pico before flashing:
#   Classroom 1 (closest to head node) → "E6-02-01"
#   Classroom 2                         → "E6-02-02"
#   Classroom 3 (furthest)              → "E6-02-03"
ROOM_ID   = "E6-02-01"
# ROOM_CODE is a 4-char compact form used inside BLE frames to save space.
# "E6-02-01" → "6201",  "E6-02-03" → "6203"
ROOM_CODE = ROOM_ID[1] + ROOM_ID[4] + ROOM_ID[-2:]   # building + floor + room digits

# ── PIR config ────────────────────────────────────────────────────────────────
PIR_PIN              = 28   # entrance door PIR (moved from GP26 to free it for heatmap)
PIR_WARMUP_MS        = 2000
PIR_DEBOUNCE_MS      = 200
PIR_QUIET_TIMEOUT_MS = 1500
IDLE_SLEEP_MS        = 200

# ── Heatmap PIR config ────────────────────────────────────────────────────────
# 4 PIR sensors mounted on the ceiling, one per zone.
# Zone layout (top-down view):   Z1(GP0)  | Z2(GP6)
#                                Z3(GP8)  | Z4(GP26)
# ↓ Change HEATMAP_INTERVAL_MS to adjust how often a report is sent (default 30s).
# ↓ Change thresholds to tune how many hits map to each score level.
HPIR_PINS           = [0, 6, 8, 26]  # GP pins for Zone 1–4
HEATMAP_INTERVAL_MS = 60_000          # send one "H" frame per minute
ZONE_HOLD_MS        = 3_000           # quiet time before a presence event ends (debounce)
ZONE_THRESH_LOW     = 3               # 1–3 events → score 1 (low)
ZONE_THRESH_MED     = 7               # 4–7 events → score 2 (medium); 8+ → score 3 (high)

# ── Ultrasonic config ─────────────────────────────────────────────────────────
TRIG1_PIN             = 3
ECHO1_PIN             = 2
TRIG2_PIN             = 5
ECHO2_PIN             = 4
THRESHOLD_CM          = 125
MAX_RANGE_CM          = 400
HIT_CONFIRM           = 2
TIMEOUT_WINDOW_MS     = 1500
MIN_INTERVAL_MS       = 1500
INTER_SENSOR_DELAY_MS = 60
LOOP_DELAY_MS         = 20

# ── Hardware ──────────────────────────────────────────────────────────────────
pir   = Pin(PIR_PIN,   Pin.IN)          # entrance door PIR (GP28)
TRIG1 = Pin(TRIG1_PIN, Pin.OUT)
ECHO1 = Pin(ECHO1_PIN, Pin.IN)
TRIG2 = Pin(TRIG2_PIN, Pin.OUT)
ECHO2 = Pin(ECHO2_PIN, Pin.IN)

# Heatmap PIR pins — one per zone
hpir0 = Pin(HPIR_PINS[0], Pin.IN)      # Zone 1 (GP0)
hpir1 = Pin(HPIR_PINS[1], Pin.IN)      # Zone 2 (GP6)
hpir2 = Pin(HPIR_PINS[2], Pin.IN)      # Zone 3 (GP8)
hpir3 = Pin(HPIR_PINS[3], Pin.IN)      # Zone 4 (GP26)

# ── BLE frame helpers ─────────────────────────────────────────────────────────
def make_frame(orig, msgid, ttl, typ, data):
    return "M1|{}|{}|{}|{}|{}".format(orig, msgid, ttl, typ, data)

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

def adv_payload_name(name_str):
    name    = name_str.encode()
    payload = bytearray(b"\x02\x01\x06")
    payload += bytearray((len(name) + 1, 0x09)) + name
    return payload

def frame_to_name(frame):
    return frame[:26]   # BLE adv payload = 31 bytes; 5 bytes overhead → 26 max name.
                        # 4-char room codes (e.g. "6201") require the full 26 chars.

# ── Ultrasonic distance ───────────────────────────────────────────────────────
def get_distance_cm(trig, echo):
    trig.low()
    time.sleep_us(2)
    trig.high()
    time.sleep_us(10)
    trig.low()
    try:
        dur = time_pulse_us(echo, 1, 30000)
    except OSError:
        return 999
    dist = (dur * 343) // 20000
    return int(dist) if 0 < dist <= MAX_RANGE_CM else 999

# ── Counting FSM ──────────────────────────────────────────────────────────────
_IDLE         = 0
_S1_TRIGGERED = 1
_S2_TRIGGERED = 2
_WAIT_CLEAR   = 3

_state          = _IDLE
_state_start_ms = 0
_last_count_ms  = 0
count           = 0
_s1_hits        = 0
_s2_hits        = 0

def reset_ultra_fsm(t_ms):
    global _state, _state_start_ms, _s1_hits, _s2_hits
    _state = _IDLE; _state_start_ms = t_ms
    _s1_hits = _s2_hits = 0

def ultrasonic_step(t_ms):
    """One FSM tick (~80 ms). Updates global `count` on ENTER/EXIT."""
    global _state, _state_start_ms, _last_count_ms, count, _s1_hits, _s2_hits

    d1 = get_distance_cm(TRIG1, ECHO1)
    time.sleep_ms(INTER_SENSOR_DELAY_MS)
    d2 = get_distance_cm(TRIG2, ECHO2)

    if _state == _IDLE:
        _s1_hits = (_s1_hits + 1) if d1 < THRESHOLD_CM else 0
        _s2_hits = (_s2_hits + 1) if d2 < THRESHOLD_CM else 0
        if _s1_hits >= HIT_CONFIRM:
            _state = _S1_TRIGGERED; _state_start_ms = t_ms
            _s1_hits = _s2_hits = 0
        elif _s2_hits >= HIT_CONFIRM:
            _state = _S2_TRIGGERED; _state_start_ms = t_ms
            _s1_hits = _s2_hits = 0

    elif _state == _S1_TRIGGERED:
        if d2 < THRESHOLD_CM and time.ticks_diff(t_ms, _last_count_ms) > MIN_INTERVAL_MS:
            count += 1
            print("ENTER → Count:", count)
            _last_count_ms = t_ms; _state = _WAIT_CLEAR
        elif time.ticks_diff(t_ms, _state_start_ms) > TIMEOUT_WINDOW_MS:
            _state = _IDLE

    elif _state == _S2_TRIGGERED:
        if d1 < THRESHOLD_CM and time.ticks_diff(t_ms, _last_count_ms) > MIN_INTERVAL_MS:
            if count > 0: count -= 1
            print("EXIT  → Count:", count)
            _last_count_ms = t_ms; _state = _WAIT_CLEAR
        elif time.ticks_diff(t_ms, _state_start_ms) > TIMEOUT_WINDOW_MS:
            _state = _IDLE

    elif _state == _WAIT_CLEAR:
        if d1 > THRESHOLD_CM and d2 > THRESHOLD_CM:
            _state = _IDLE

    time.sleep_ms(LOOP_DELAY_MS)

# ── PIR session gating ────────────────────────────────────────────────────────
_pir_motion_flag  = False
_last_pir_irq_ms  = 0
_last_pir_high_ms = 0

def pir_irq_handler(pin):
    global _pir_motion_flag, _last_pir_irq_ms
    t = time.ticks_ms()
    if time.ticks_diff(t, _last_pir_irq_ms) > PIR_DEBOUNCE_MS:
        _pir_motion_flag = True
        _last_pir_irq_ms = t

try:
    pir.irq(trigger=Pin.IRQ_RISING, handler=pir_irq_handler)
except Exception:
    pass

# ── Heatmap zone tracking ─────────────────────────────────────────────────────
# Presence-hold debounce (no IRQs):
#   - Zone goes "hot"  on first high reading  → count +1 (one presence event)
#   - Zone stays "hot" while PIR keeps firing → no extra count
#   - Zone goes "cold" after ZONE_HOLD_MS of silence → ready for next person
# The main loop polls the pins every tick and resets counters every 30 s.
_zone_hits           = [0, 0, 0, 0]
_zone_active         = [False, False, False, False]  # True while zone is "hot"
_zone_last_ms        = [0, 0, 0, 0]                 # last time each zone saw motion
_last_heatmap_ms     = 0
_last_heatmap_scores = [0, 0, 0, 0]   # scores from the previous interval

def _zone_score(hits):
    """Map raw hit count in window to display score 0–3."""
    if hits == 0:                    return 0
    elif hits <= ZONE_THRESH_LOW:    return 1
    elif hits <= ZONE_THRESH_MED:    return 2
    else:                            return 3

# ── Mesh node class ───────────────────────────────────────────────────────────
class SensorNode:
    def __init__(self):
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.irq(self._irq)

        self._adv_active  = False
        self._adv_stop_ms = 0
        self.seen         = []

        # Frames queued by IRQ to be forwarded in the main loop
        # (IRQ context must stay short — no advertising inside IRQ)
        self._fwd_queue = []

        self._msgid_ctr = 0

        self.scan()
        print("Sensor Node ID:", NODE_ID, " Room:", ROOM_ID)

    # ── BLE scan ─────────────────────────────────────────────────────────────
    def scan(self):
        self.ble.gap_scan(SCAN_MS, 30000, 30000)

    # ── BLE advertise burst ───────────────────────────────────────────────────
    def advertise_burst_start(self, frame):
        payload = adv_payload_name(frame_to_name(frame))
        self.ble.gap_advertise(ADV_INTERVAL_US, adv_data=payload)
        self._adv_active  = True
        self._adv_stop_ms = time.ticks_add(time.ticks_ms(), ADV_BURST_MS)

    def advertise_burst_service(self):
        """Call every main loop tick to stop burst when window expires."""
        if self._adv_active and time.ticks_diff(time.ticks_ms(), self._adv_stop_ms) >= 0:
            self.ble.gap_advertise(None)
            self._adv_active = False

    # ── Dedup cache ───────────────────────────────────────────────────────────
    def seen_check_add(self, key):
        if key in self.seen:
            return True
        self.seen.append(key)
        if len(self.seen) > SEEN_MAX:
            del self.seen[0: len(self.seen) - SEEN_MAX]
        return False

    # ── Inject own count frame ────────────────────────────────────────────────
    def inject_count(self, c):
        # msgid capped at 0xFFF (4095) so it never exceeds 4 digits.
        # With ROOM_CODE (3 chars) the worst-case frame is:
        #   M1|abc123|4095|3|C|6201:99  =  26 chars  ← fits at BLE max
        self._msgid_ctr = (self._msgid_ctr + 1) & 0xFFF
        data  = "{}:{}".format(ROOM_CODE, c)   # e.g. "601:5"
        frame = make_frame(NODE_ID, str(self._msgid_ctr), DEFAULT_TTL, "C", data)
        self.seen_check_add("{}:{}".format(NODE_ID, self._msgid_ctr))
        self.advertise_burst_start(frame)
        print("TX  {} ({}) count={}".format(ROOM_ID, ROOM_CODE, c))

    # ── Inject heatmap frame ──────────────────────────────────────────────────
    def inject_heatmap(self, scores):
        # Pack 4 zone scores (0–3 each, 2 bits each) into 1 byte → 2 hex chars.
        # bits[7:6]=Z1, bits[5:4]=Z2, bits[3:2]=Z3, bits[1:0]=Z4
        # Worst-case frame: M1|abc123|4095|3|H|6201:FF = 26 chars ✓
        self._msgid_ctr = (self._msgid_ctr + 1) & 0xFFF
        packed = (scores[0] << 6) | (scores[1] << 4) | (scores[2] << 2) | scores[3]
        data   = "{}:{:02X}".format(ROOM_CODE, packed)
        frame  = make_frame(NODE_ID, str(self._msgid_ctr), DEFAULT_TTL, "H", data)
        self.seen_check_add("{}:{}".format(NODE_ID, self._msgid_ctr))
        self.advertise_burst_start(frame)
        print("TX  HMAP {} zones={}".format(ROOM_CODE, scores))

    # ── Forward a received frame (TTL-1) ──────────────────────────────────────
    def forward_ttl(self, orig, msgid, ttl, typ, data):
        ttl2 = ttl - 1
        if ttl2 < 0:
            return
        fwd = make_frame(orig, msgid, ttl2, typ, data)
        self.advertise_burst_start(fwd)
        print("FWD ttl={} orig={}".format(ttl2, orig))

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

            # Only relay count ("C") and heatmap ("H") frames
            if typ not in ("C", "H"):
                return

            # Ignore own frames
            if orig == NODE_ID:
                return

            key = "{}:{}".format(orig, msgid)
            if self.seen_check_add(key):
                return   # duplicate — already relayed

            # Queue relay for main loop (keep IRQ short)
            if ttl > 0:
                self._fwd_queue.append((orig, msgid, ttl, typ, payload))

        elif event == _IRQ_SCAN_DONE:
            self.scan()

    # ── Main loop ─────────────────────────────────────────────────────────────
    def run(self):
        global _pir_motion_flag, _last_pir_high_ms
        global _last_heatmap_ms, _last_heatmap_scores
        global _zone_hits, _zone_active, _zone_last_ms

        session_active    = False
        reset_ultra_fsm(time.ticks_ms())
        prev_count        = count
        _last_heatmap_ms  = time.ticks_ms()

        while True:
            t = time.ticks_ms()

            # ── Service BLE burst window ──────────────────────────────────────
            self.advertise_burst_service()

            # ── Drain relay queue (only when not currently advertising) ───────
            if self._fwd_queue and not self._adv_active:
                orig, msgid, ttl, typ, payload = self._fwd_queue.pop(0)
                self.forward_ttl(orig, msgid, ttl, typ, payload)

            # ── PIR ───────────────────────────────────────────────────────────
            pir_val = pir.value()
            if pir_val == 1:
                _last_pir_high_ms = t
            if _pir_motion_flag:
                _pir_motion_flag  = False
                _last_pir_high_ms = t

            # ── Start/stop ultrasonic session ─────────────────────────────────
            if not session_active and (
                time.ticks_diff(t, _last_pir_high_ms) <= PIR_DEBOUNCE_MS or pir_val == 1
            ):
                session_active = True
                print("Motion → counting ON")
                reset_ultra_fsm(t)

            if session_active:
                ultrasonic_step(t)   # ~80 ms per call
                if time.ticks_diff(t, _last_pir_high_ms) > PIR_QUIET_TIMEOUT_MS:
                    session_active = False
                    print("No motion → counting OFF")
                    reset_ultra_fsm(t)
            else:
                # Only sleep when NOT advertising — lightsleep suspends the CYW43
                # radio, which would cut the 300ms BLE burst short and cause the
                # head node to miss the frame entirely.
                if not self._adv_active:
                    try:
                        machine.lightsleep(IDLE_SLEEP_MS)
                    except Exception:
                        time.sleep_ms(IDLE_SLEEP_MS)
                else:
                    time.sleep_ms(10)   # stay awake; burst will end shortly

            # ── Heatmap zone polling (presence-hold debounce) ─────────────────
            for _i, _hpin in enumerate((hpir0, hpir1, hpir2, hpir3)):
                if _hpin.value() == 1:
                    _zone_last_ms[_i] = t
                    if not _zone_active[_i]:
                        _zone_active[_i] = True
                        _zone_hits[_i] += 1     # new presence event — count once
                elif _zone_active[_i] and time.ticks_diff(t, _zone_last_ms[_i]) >= ZONE_HOLD_MS:
                    _zone_active[_i] = False    # zone went cold — ready for next person

            # ── Inject own count frame on change ──────────────────────────────
            if count != prev_count:
                prev_count = count
                self.inject_count(count)

            # ── Heatmap heartbeat (every 30 s) ────────────────────────────────
            if time.ticks_diff(t, _last_heatmap_ms) >= HEATMAP_INTERVAL_MS:
                scores = [_zone_score(_zone_hits[i]) for i in range(4)]
                _zone_hits[0] = _zone_hits[1] = _zone_hits[2] = _zone_hits[3] = 0
                _last_heatmap_ms = t
                # Skip if this interval AND the last were both all-zero (room empty).
                # Always send once when transitioning from active → empty so the
                # dashboard clears; skip every subsequent all-zero frame after that.
                was_empty = not any(_last_heatmap_scores)
                is_empty  = not any(scores)
                if not (was_empty and is_empty):
                    self.inject_heatmap(scores)   # always inject — same as inject_count
                _last_heatmap_scores[:] = scores

# ── Boot ──────────────────────────────────────────────────────────────────────
print("Warming up PIR...")
time.sleep_ms(PIR_WARMUP_MS)
print("Ready")

node = SensorNode()
node.run()
