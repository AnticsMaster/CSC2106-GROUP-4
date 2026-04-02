# sensor_pico.py  –  Unified Sensor Pico (config-driven)
#
# Dual role:
#   1. Door PIR + 2× ultrasonic for entrance/exit counting
#   2. 4× heatmap PIRs (one per zone) for classroom activity heatmap
#   3. BLE mesh relay — forwards other classrooms' frames toward the head node
#
# ── HOW TO DEPLOY TO A NEW ROOM ───────────────────────────────────────────────
# 1. Copy this file to the Pico (no changes needed).
# 2. Create config.json on the Pico's flash with the room identity:
#
#      {
#        "room_id": "E3-02-01"
#      }
#
#    Format: "E<building>-<floor>-<room>", e.g. "E3-02-01", "E6-03-02"
# 3. Power on. Done — no other changes needed anywhere.
# ─────────────────────────────────────────────────────────────────────────────

import bluetooth
import time
import ubinascii
import ujson
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

# ── PIR config ────────────────────────────────────────────────────────────────
PIR_PIN              = 28
PIR_WARMUP_MS        = 2000
PIR_DEBOUNCE_MS      = 200
PIR_QUIET_TIMEOUT_MS = 1500
IDLE_SLEEP_MS        = 200

# ── Heatmap PIR config ────────────────────────────────────────────────────────
HPIR_PINS           = [0, 6, 8, 26]  # GP pins for Zone 1–4
HEATMAP_INTERVAL_MS = 60_000
ZONE_HOLD_MS        = 3_000
ZONE_THRESH_LOW     = 3
ZONE_THRESH_MED     = 7

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

# ── Load config ───────────────────────────────────────────────────────────────
def load_config():
    try:
        with open("config.json") as f:
            return ujson.load(f)
    except Exception:
        raise RuntimeError("Missing config.json — create it with {\"room_id\": \"E<b>-<fl>-<rm>\"}")

cfg = load_config()
ROOM_ID = cfg["room_id"]
# ROOM_CODE: 4-char compact form used inside BLE frames.
# "E2-02-01" → "2201",  "E6-03-02" → "6302"
ROOM_CODE = ROOM_ID[1] + ROOM_ID[4] + ROOM_ID[-2:]

# ── Node identity (stable across reboots — derived from hardware UID) ─────────
NODE_ID = ubinascii.hexlify(machine.unique_id()).decode()[-6:]

# ── Hardware ──────────────────────────────────────────────────────────────────
pir   = Pin(PIR_PIN,   Pin.IN)
TRIG1 = Pin(TRIG1_PIN, Pin.OUT)
ECHO1 = Pin(ECHO1_PIN, Pin.IN)
TRIG2 = Pin(TRIG2_PIN, Pin.OUT)
ECHO2 = Pin(ECHO2_PIN, Pin.IN)

hpir0 = Pin(HPIR_PINS[0], Pin.IN)
hpir1 = Pin(HPIR_PINS[1], Pin.IN)
hpir2 = Pin(HPIR_PINS[2], Pin.IN)
hpir3 = Pin(HPIR_PINS[3], Pin.IN)

# ── BLE Protocol Constants ───────────────────────────────────────────────────
PROTOCOL_VERSION = 0xA1
BLE_ENC_KEY = b"1234567890ABCDEF"  # Replace with secure key
BLE_MAC_KEY = b"FEDCBA0987654321"  # Replace with secure key
COMPANY_ID = b"\x12\x34"  # Placeholder company ID

# ── Helper Functions ─────────────────────────────────────────────────────────
def pack_classroom_id(is_west, block_num, level, room_num):
    packed = (is_west << 12) | (block_num << 9) | (level << 5) | room_num
    return packed.to_bytes(2, "big")

def unpack_classroom_id(packed):
    value = int.from_bytes(packed, "big")
    is_west = (value >> 12) & 0x1
    block_num = (value >> 9) & 0x7
    level = (value >> 5) & 0xF
    room_num = value & 0x1F
    return is_west, block_num, level, room_num

def build_nonce(unique_id, msgid, ttl_type):
    return unique_id + msgid.to_bytes(2, "big") + bytes([ttl_type]) + bytes(5)

def encrypt_data(plaintext, unique_id, msgid, ttl_type):
    nonce = build_nonce(unique_id, msgid, ttl_type)
    aes = ucryptolib.aes(BLE_ENC_KEY, 1, nonce)  # AES ECB mode
    keystream = aes.encrypt(bytes(16))
    return bytes([p ^ k for p, k in zip(plaintext, keystream[:4])])

def compute_auth_tag(header, ciphertext):
    h = uhashlib.sha256()
    h.update(BLE_MAC_KEY + header + ciphertext)
    return h.digest()[:4]

def build_frame(unique_id, msgid, ttl, typ, plaintext):
    ttl_type = (ttl << 4) | typ
    ciphertext = encrypt_data(plaintext, unique_id, msgid, ttl_type)
    header = bytes([PROTOCOL_VERSION]) + unique_id + msgid.to_bytes(2, "big") + bytes([ttl_type])
    tag = compute_auth_tag(header, ciphertext)
    return header + ciphertext + tag

def parse_frame(frame):
    if len(frame) != 20 or frame[0] != PROTOCOL_VERSION:
        return None
    unique_id = frame[1:9]
    msgid = int.from_bytes(frame[9:11], "big")
    ttl_type = frame[11]
    ttl = ttl_type >> 4
    typ = ttl_type & 0xF
    ciphertext = frame[12:16]
    tag = frame[16:20]
    header = frame[:12]
    computed_tag = compute_auth_tag(header, ciphertext)
    if tag != computed_tag:
        return None
    return unique_id, msgid, ttl, typ, ciphertext

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
_zone_hits           = [0, 0, 0, 0]
_zone_active         = [False, False, False, False]
_zone_last_ms        = [0, 0, 0, 0]
_last_heatmap_ms     = 0
_last_heatmap_scores = [0, 0, 0, 0]

def _zone_score(hits):
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
        self._fwd_queue   = []
        self._msgid_ctr   = 0

        self.scan()
        print("Sensor Node ID:", NODE_ID, " Room:", ROOM_ID, " Code:", ROOM_CODE)

    def scan(self):
        self.ble.gap_scan(SCAN_MS, 30000, 30000)

    def advertise_burst_start(self, frame):
        payload = adv_payload_name(frame_to_name(frame))
        self.ble.gap_advertise(ADV_INTERVAL_US, adv_data=payload)
        self._adv_active  = True
        self._adv_stop_ms = time.ticks_add(time.ticks_ms(), ADV_BURST_MS)

    def advertise_burst_service(self):
        if self._adv_active and time.ticks_diff(time.ticks_ms(), self._adv_stop_ms) >= 0:
            self.ble.gap_advertise(None)
            self._adv_active = False

    def seen_check_add(self, key):
        if key in self.seen:
            return True
        self.seen.append(key)
        if len(self.seen) > SEEN_MAX:
            del self.seen[0: len(self.seen) - SEEN_MAX]
        return False

    def inject_count(self, c):
        self._msgid_ctr = (self._msgid_ctr + 1) & 0xFFF
        data  = "{}:{}".format(ROOM_CODE, c)
        frame = build_frame(NODE_ID, str(self._msgid_ctr), DEFAULT_TTL, "C", data)
        self.seen_check_add("{}:{}".format(NODE_ID, self._msgid_ctr))
        self.advertise_burst_start(frame)
        print("TX  {} ({}) count={}".format(ROOM_ID, ROOM_CODE, c))

    def inject_heatmap(self, scores):
        self._msgid_ctr = (self._msgid_ctr + 1) & 0xFFF
        packed = (scores[0] << 6) | (scores[1] << 4) | (scores[2] << 2) | scores[3]
        data   = "{}:{:02X}".format(ROOM_CODE, packed)
        frame  = build_frame(NODE_ID, str(self._msgid_ctr), DEFAULT_TTL, "H", data)
        self.seen_check_add("{}:{}".format(NODE_ID, self._msgid_ctr))
        self.advertise_burst_start(frame)
        print("TX  HMAP {} zones={}".format(ROOM_CODE, scores))

    def forward_ttl(self, orig, msgid, ttl, typ, data):
        ttl2 = ttl - 1
        if ttl2 < 0:
            return
        fwd = build_frame(orig, msgid, ttl2, typ, data)
        self.advertise_burst_start(fwd)
        print("FWD ttl={} orig={}".format(ttl2, orig))

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

            if typ not in ("C", "H"):
                return

            if orig == NODE_ID:
                return

            key = "{}:{}".format(orig, msgid)
            if self.seen_check_add(key):
                return

            if ttl > 0:
                self._fwd_queue.append((orig, msgid, ttl, typ, payload))

        elif event == _IRQ_SCAN_DONE:
            self.scan()

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

            self.advertise_burst_service()

            if self._fwd_queue and not self._adv_active:
                orig, msgid, ttl, typ, payload = self._fwd_queue.pop(0)
                self.forward_ttl(orig, msgid, ttl, typ, payload)

            pir_val = pir.value()
            if pir_val == 1:
                _last_pir_high_ms = t
            if _pir_motion_flag:
                _pir_motion_flag  = False
                _last_pir_high_ms = t

            if not session_active and (
                time.ticks_diff(t, _last_pir_high_ms) <= PIR_DEBOUNCE_MS or pir_val == 1
            ):
                session_active = True
                print("Motion → counting ON")
                reset_ultra_fsm(t)

            if session_active:
                ultrasonic_step(t)
                if time.ticks_diff(t, _last_pir_high_ms) > PIR_QUIET_TIMEOUT_MS:
                    session_active = False
                    print("No motion → counting OFF")
                    reset_ultra_fsm(t)
            else:
                if not self._adv_active:
                    try:
                        machine.lightsleep(IDLE_SLEEP_MS)
                    except Exception:
                        time.sleep_ms(IDLE_SLEEP_MS)
                else:
                    time.sleep_ms(10)

            for _i, _hpin in enumerate((hpir0, hpir1, hpir2, hpir3)):
                if _hpin.value() == 1:
                    _zone_last_ms[_i] = t
                    if not _zone_active[_i]:
                        _zone_active[_i] = True
                        _zone_hits[_i] += 1
                elif _zone_active[_i] and time.ticks_diff(t, _zone_last_ms[_i]) >= ZONE_HOLD_MS:
                    _zone_active[_i] = False

            if count != prev_count:
                prev_count = count
                self.inject_count(count)

            if time.ticks_diff(t, _last_heatmap_ms) >= HEATMAP_INTERVAL_MS:
                scores = [_zone_score(_zone_hits[i]) for i in range(4)]
                _zone_hits[0] = _zone_hits[1] = _zone_hits[2] = _zone_hits[3] = 0
                _last_heatmap_ms = t
                was_empty = not any(_last_heatmap_scores)
                is_empty  = not any(scores)
                if not (was_empty and is_empty):
                    self.inject_heatmap(scores)
                _last_heatmap_scores[:] = scores

# ── Boot ──────────────────────────────────────────────────────────────────────
print("Warming up PIR...")
time.sleep_ms(PIR_WARMUP_MS)
print("Room:", ROOM_ID, "  Code:", ROOM_CODE)

node = SensorNode()
node.run()
