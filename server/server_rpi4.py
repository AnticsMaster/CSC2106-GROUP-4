# server_rpi4.py  –  MQTT Broker + Mesh Coordinator
# Multi-Cluster Hybrid Mesh Network  |  CSC2106 Group 4
# Runs on Raspberry Pi 4 (CPython / Linux)
#
# This Pi IS the broker. Root A, Root B, and all child nodes
# connect to this device's IP on port 1883.
#
# Topology
#               SERVER  ← this file
#              /        \
#          Root A       Root B          connect to this broker
#          /    \       /    \
#        A1 -- A2     B1 -- B2          connect to this broker
#          \  /           \  /
#           A4             B3           connect to this broker
#
# Install dependency:  pip install RPi.GPIO
# Run with:           python3 server_rpi4.py

import select
import socket
import time

try:
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    print("[BROKER] RPi.GPIO not available — LED control disabled")

# ── Config ─────────────────────────────────────────────────────────────────────
PORT        = 1883
MAX_CLIENTS = 12

# BCM GPIO pin numbers — adjust to match your wiring
PIN_LED_A     = 14   # HIGH = Cluster A has a live root
PIN_LED_B     = 15   # HIGH = Cluster B has a live root
PIN_LED_BOARD = 25   # blinks to show main loop is alive (connect an LED here)

# ── MQTT packet type IDs (upper nibble of fixed header) ────────────────────────
T_CONNECT    = 1;  T_CONNACK  = 2
T_PUBLISH    = 3;  T_PUBACK   = 4
T_SUBSCRIBE  = 8;  T_SUBACK   = 9
T_PINGREQ    = 12; T_PINGRESP = 13
T_DISCONNECT = 14

# ── Broker state ───────────────────────────────────────────────────────────────
buffers  = {}   # sock → bytearray
clients  = {}   # sock → {id, subs:[(topic,qos)], will_topic, will_msg,
                #                   will_retain, will_qos}
retained = {}   # topic → bytes
fd_map   = {}   # fd (int) → socket object  (needed because select.poll returns fds)

# ── Coordinator state ──────────────────────────────────────────────────────────
cluster_A = {'root': 'devA', 'online': False}
cluster_B = {'root': 'devB', 'online': False}

# ── GPIO helpers ───────────────────────────────────────────────────────────────
def gpio_setup():
    if not GPIO_AVAILABLE:
        return
    for pin in (PIN_LED_A, PIN_LED_B, PIN_LED_BOARD):
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

def led_set(pin, state):
    if GPIO_AVAILABLE:
        GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)

gpio_setup()

# ── Time helpers (replaces MicroPython ticks_ms / ticks_diff) ─────────────────
def ticks_ms():
    return time.monotonic_ns() // 1_000_000

def ticks_diff(a, b):
    return a - b

# ── Get local IP ───────────────────────────────────────────────────────────────
def get_local_ip():
    """Return the primary non-loopback IP by probing a UDP route."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# ── MQTT encoding helpers ──────────────────────────────────────────────────────
def encode_varlen(n):
    """Encode an integer as MQTT variable-length bytes."""
    out = []
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)

def rd_u16(buf, pos):
    return (buf[pos] << 8) | buf[pos + 1], pos + 2

def rd_str(buf, pos):
    n, pos = rd_u16(buf, pos)
    return bytes(buf[pos: pos + n]), pos + n

def topic_match(pattern, topic):
    """MQTT wildcard matching — supports + (single level) and # (multi-level)."""
    pp = pattern.split('/')
    tp = topic.split('/')
    i = 0
    for p in pp:
        if p == '#':
            return True
        if i >= len(tp):
            return False
        if p != '+' and p != tp[i]:
            return False
        i += 1
    return i == len(tp)

def mk_publish(topic, payload, qos=0, retain=False, pid=1):
    if isinstance(topic, str):
        topic = topic.encode()
    if isinstance(payload, str):
        payload = payload.encode()
    fh   = (T_PUBLISH << 4) | (retain & 1) | ((qos & 3) << 1)
    body = bytes([len(topic) >> 8, len(topic) & 0xFF]) + topic
    if qos:
        body += bytes([pid >> 8, pid & 0xFF])
    body += payload
    return bytes([fh]) + encode_varlen(len(body)) + body

# ── Forward a published message to all matching subscribers ────────────────────
def forward(topic, payload, qos=0, retain=False):
    if isinstance(topic, bytes):
        topic = topic.decode()
    for sock, info in list(clients.items()):
        for sub, sub_qos in info['subs']:
            if topic_match(sub, topic):
                try:
                    sock.sendall(mk_publish(topic, payload, min(qos, sub_qos), retain))
                except Exception as e:
                    print(f"[BROKER] send error to {info['id']}: {e}")
                break

# ── MQTT packet handlers ───────────────────────────────────────────────────────
def handle_connect(sock, pkt, pos):
    _, pos    = rd_str(pkt, pos)     # protocol name  (e.g. "MQTT")
    pos      += 1                    # protocol level (4 for MQTT 3.1.1)
    flags     = pkt[pos]; pos += 1
    pos      += 2                    # keep-alive (2 bytes, ignored)

    cid_b, pos = rd_str(pkt, pos)
    cid        = cid_b.decode()

    will_topic = will_msg = None
    will_retain = False; will_qos = 0

    if flags & 0x04:                 # Will flag
        will_qos    = (flags >> 3) & 0x03
        will_retain = bool(flags & 0x20)
        wt, pos     = rd_str(pkt, pos); will_topic = wt.decode()
        wm, pos     = rd_str(pkt, pos); will_msg   = bytes(wm)

    if flags & 0x80: _, pos = rd_str(pkt, pos)  # username (skip)
    if flags & 0x40: _, pos = rd_str(pkt, pos)  # password (skip)

    clients[sock] = dict(
        id=cid, subs=[],
        will_topic=will_topic, will_msg=will_msg,
        will_retain=will_retain, will_qos=will_qos,
    )
    sock.sendall(bytes([T_CONNACK << 4, 2, 0, 0]))
    print(f"[BROKER] CONNECT   {cid}")

def handle_publish(sock, fh_flags, pkt, pos, end):
    qos    = (fh_flags >> 1) & 0x03
    retain = fh_flags & 0x01

    topic_b, pos = rd_str(pkt, pos)
    topic        = topic_b.decode()

    pid = 0
    if qos:
        pid, pos = rd_u16(pkt, pos)

    payload = bytes(pkt[pos:end])
    print(f"[BROKER] PUBLISH   {topic}  →  {payload}")

    # Update retained store
    if retain:
        if payload:
            retained[topic] = payload
        elif topic in retained:
            del retained[topic]

    # PUBACK for QoS 1
    if qos == 1:
        sock.sendall(bytes([T_PUBACK << 4, 2, pid >> 8, pid & 0xFF]))

    # Deliver to subscribers, then run coordinator logic
    forward(topic, payload, qos, bool(retain))
    coordinate(topic, payload)

def handle_subscribe(sock, pkt, pos, end):
    pid, pos = rd_u16(pkt, pos)
    granted  = []

    while pos < end:
        t_b, pos = rd_str(pkt, pos)
        q        = pkt[pos]; pos += 1
        t        = t_b.decode()
        clients[sock]['subs'].append((t, q))
        granted.append(min(q, 1))
        print(f"[BROKER] SUBSCRIBE {clients[sock]['id']}  →  {t}  qos={q}")

        # Deliver any matching retained messages
        for rt, rp in retained.items():
            if rp and topic_match(t, rt):
                try:
                    sock.sendall(mk_publish(rt, rp, 0, True))
                except Exception:
                    pass

    sock.sendall(bytes([T_SUBACK << 4, 2 + len(granted),
                        pid >> 8, pid & 0xFF] + granted))

# ── Socket lifecycle ───────────────────────────────────────────────────────────
def close_sock(sock, clean=False):
    """Publish LWT (if any) and clean up the socket."""
    info = clients.pop(sock, None)
    if info:
        print(f"[BROKER] {'DISCONNECT' if clean else 'LOST'}  {info['id']}")
        if not clean and info['will_topic']:
            wm = info['will_msg'] or b''
            if info['will_retain']:
                retained[info['will_topic']] = wm
            forward(info['will_topic'], wm, info['will_qos'])
            coordinate(info['will_topic'], wm)
    buffers.pop(sock, None)
    fd_map.pop(sock.fileno(), None)
    try:
        sock.close()
    except Exception:
        pass

# ── Parse one complete MQTT packet from buf ────────────────────────────────────
# Returns:  n > 0  → consumed n bytes (keep processing)
#           0      → buffer incomplete (wait for more data)
#          -1      → protocol error / clean disconnect (close socket)
def try_parse(sock, buf):
    if len(buf) < 2:
        return 0

    # Decode variable-length remaining-length field (max 4 bytes)
    remaining = 0; shift = 0; idx = 1
    while True:
        if idx >= len(buf):
            return 0
        b     = buf[idx]; idx += 1
        remaining |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
        if shift > 21:       # malformed packet
            return -1

    total = idx + remaining
    if len(buf) < total:
        return 0             # not enough data yet

    fh    = buf[0]
    ptype = fh >> 4
    flags = fh & 0x0F
    pos   = idx
    end   = total

    # Reject anything except CONNECT before the client is registered
    if ptype != T_CONNECT and sock not in clients:
        return -1

    try:
        if ptype == T_CONNECT:
            handle_connect(sock, buf, pos)
        elif ptype == T_PUBLISH:
            handle_publish(sock, flags, buf, pos, end)
        elif ptype == T_SUBSCRIBE:
            handle_subscribe(sock, buf, pos, end)
        elif ptype == T_PINGREQ:
            sock.sendall(bytes([T_PINGRESP << 4, 0]))
        elif ptype == T_DISCONNECT:
            close_sock(sock, clean=True)
            return -1
        # PUBACK / UNSUBSCRIBE / etc. — acknowledged, no action needed
    except Exception as e:
        print(f"[BROKER] parse error ptype={ptype}: {e}")
        return -1

    return total

# ── Coordination logic (runs on every published message) ──────────────────────
def coordinate(topic, payload):
    msg = payload.decode('utf-8', 'ignore') if isinstance(payload, (bytes, bytearray)) else str(payload)

    # ── Root A health ──────────────────────────────────────────────────────────
    if topic == 'csc2106/devA/status':
        if msg == 'online':
            cluster_A['online'] = True
            led_set(PIN_LED_A, True)
            print("[COORD] Cluster A root ONLINE")
        elif msg == 'offline':
            cluster_A['online'] = False
            led_set(PIN_LED_A, False)
            print("[COORD] Cluster A root OFFLINE — triggering election")
            forward('csc2106/clusterA/election', b'ELECT', qos=1)

    # ── Root B health ──────────────────────────────────────────────────────────
    elif topic == 'csc2106/devB/status':
        if msg == 'online':
            cluster_B['online'] = True
            led_set(PIN_LED_B, True)
            print("[COORD] Cluster B root ONLINE")
        elif msg == 'offline':
            cluster_B['online'] = False
            led_set(PIN_LED_B, False)
            print("[COORD] Cluster B root OFFLINE — triggering election")
            forward('csc2106/clusterB/election', b'ELECT', qos=1)

    # ── Election results ───────────────────────────────────────────────────────
    elif topic == 'csc2106/clusterA/elected':
        cluster_A.update(root=msg, online=True)
        led_set(PIN_LED_A, True)
        retained['csc2106/clusterA/root'] = payload
        print(f"[COORD] Cluster A new root elected: {msg}")
        forward('csc2106/clusterA/root', payload, retain=True)

    elif topic == 'csc2106/clusterB/elected':
        cluster_B.update(root=msg, online=True)
        led_set(PIN_LED_B, True)
        retained['csc2106/clusterB/root'] = payload
        print(f"[COORD] Cluster B new root elected: {msg}")
        forward('csc2106/clusterB/root', payload, retain=True)

    # ── Cross-cluster routing  A → B ──────────────────────────────────────────
    elif topic.startswith('csc2106/clusterA/to/clusterB/'):
        sub   = topic[len('csc2106/clusterA/to/clusterB/'):]
        relay = f"csc2106/{cluster_B['root']}/relay/{sub}"
        print(f"[COORD] Route A→B  →  {relay}")
        forward(relay, payload, qos=1)

    # ── Cross-cluster routing  B → A ──────────────────────────────────────────
    elif topic.startswith('csc2106/clusterB/to/clusterA/'):
        sub   = topic[len('csc2106/clusterB/to/clusterA/'):]
        relay = f"csc2106/{cluster_A['root']}/relay/{sub}"
        print(f"[COORD] Route B→A  →  {relay}")
        forward(relay, payload, qos=1)

    # ── Building A head node status (E2-02-01) ─────────────────────────────────
    elif topic == 'csc2106/classroom/E2-02-01/HeadNode-E2/status':
        if msg == 'online':
            print("[COORD] Building E2 HeadNode-E2 ONLINE")
        elif msg == 'offline':
            print("[COORD] Building E2 HeadNode-E2 OFFLINE — sensor will fail over to BackUp-E2")

    elif topic == 'csc2106/classroom/E2-02-01/BackUp-E2/status':
        if msg == 'online':
            print("[COORD] Building E2 BackUp-E2 ONLINE")
        elif msg == 'offline':
            print("[COORD] Building E2 BackUp-E2 OFFLINE — sensor will fail over to HeadNode-E2")

    # ── Building B head node status (E6-02-02) ─────────────────────────────────
    elif topic == 'csc2106/classroom/E6-02-02/HeadNode-E6/status':
        if msg == 'online':
            print("[COORD] Building E6 HeadNode-E6 ONLINE")
        elif msg == 'offline':
            print("[COORD] Building E6 HeadNode-E6 OFFLINE — sensor will fail over to Backup-E6")

    elif topic == 'csc2106/classroom/E6-02-02/Backup-E6/status':
        if msg == 'online':
            print("[COORD] Building E6 Backup-E6 ONLINE")
        elif msg == 'offline':
            print("[COORD] Building E6 Backup-E6 OFFLINE — sensor will fail over to HeadNode-E6")

# ── Main ───────────────────────────────────────────────────────────────────────
ip = get_local_ip()
print(f"[BROKER] Local IP: {ip}  (set this as BROKER_IP on all nodes)")

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('', PORT))
srv.listen(MAX_CLIENTS)
srv.setblocking(False)

poll = select.poll()
poll.register(srv.fileno(), select.POLLIN)
fd_map[srv.fileno()] = srv

print(f"[BROKER] Listening on port {PORT}  —  max {MAX_CLIENTS} clients")

blink_state = False
last_blink  = ticks_ms()

try:
    while True:
        events = poll.poll(50)   # 50 ms timeout keeps the blink responsive

        for fd, ev in events:
            obj = fd_map.get(fd)
            if obj is None:
                continue

            # ── Accept new connection ──────────────────────────────────────────
            if obj is srv:
                try:
                    conn, addr = srv.accept()
                    conn.setblocking(False)
                    buffers[conn] = bytearray()
                    poll.register(conn.fileno(), select.POLLIN)
                    fd_map[conn.fileno()] = conn
                    print(f"[BROKER] New connection from {addr[0]}:{addr[1]}")
                except Exception as e:
                    print("[BROKER] accept error:", e)

            # ── Data from an existing client ───────────────────────────────────
            else:
                sock = obj
                try:
                    data = sock.recv(512)
                except BlockingIOError:
                    continue    # EAGAIN — spurious wake-up
                except OSError:
                    data = None

                if data is None:
                    continue

                if not data:
                    # Empty read = connection closed by peer
                    try:
                        poll.unregister(fd)
                    except Exception:
                        pass
                    close_sock(sock)
                    continue

                buffers.setdefault(sock, bytearray())
                buffers[sock].extend(data)

                # Drain all complete packets from the buffer
                while True:
                    n = try_parse(sock, buffers[sock])
                    if n > 0:
                        buffers[sock] = buffers[sock][n:]
                    elif n == 0:
                        break           # wait for more bytes
                    else:               # -1 → close socket
                        try:
                            poll.unregister(fd)
                        except Exception:
                            pass
                        close_sock(sock)
                        break

        # ── Heartbeat blink ────────────────────────────────────────────────────
        now = ticks_ms()
        if ticks_diff(now, last_blink) >= 500:
            blink_state = not blink_state
            led_set(PIN_LED_BOARD, blink_state)
            last_blink = now

finally:
    if GPIO_AVAILABLE:
        GPIO.cleanup()
    srv.close()
