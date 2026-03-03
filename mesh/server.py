# server.py  –  MQTT Broker + Mesh Coordinator
# Multi-Cluster Hybrid Mesh Network  |  CSC2106 Group 4
# Runs on Raspberry Pi Pico W (MicroPython)
#
# This Pico IS the broker. Root A, Root B, and all child nodes
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

import uselect
import usocket as socket
import network
import time
from machine import Pin

# ── Config ─────────────────────────────────────────────────────────────────────
WIFI_SSID     = "Danwifi"
WIFI_PASSWORD = "wifiisgood"
PORT          = 1883
MAX_CLIENTS   = 12

# ── MQTT packet type IDs (upper nibble of fixed header) ────────────────────────
T_CONNECT    = 1;  T_CONNACK  = 2
T_PUBLISH    = 3;  T_PUBACK   = 4
T_SUBSCRIBE  = 8;  T_SUBACK   = 9
T_PINGREQ    = 12; T_PINGRESP = 13
T_DISCONNECT = 14

# ── Broker state ───────────────────────────────────────────────────────────────
# buffers  : accumulate partial TCP data per socket (includes pre-CONNECT socks)
# clients  : filled after CONNECT packet is parsed
# retained : last retained payload per topic
buffers  = {}   # sock → bytearray
clients  = {}   # sock → {id, subs:[(topic,qos)], will_topic, will_msg,
                #                   will_retain, will_qos}
retained = {}   # topic → bytes

# ── Coordinator state ──────────────────────────────────────────────────────────
cluster_A = {'root': 'devA', 'online': False}
cluster_B = {'root': 'devB', 'online': False}

led_a     = Pin(14, Pin.OUT)   # HIGH = Cluster A has a live root
led_b     = Pin(15, Pin.OUT)   # HIGH = Cluster B has a live root
led_board = Pin("LED", Pin.OUT)  # blinks to show main loop is alive

led_a.off(); led_b.off(); led_board.off()

# ── WiFi ───────────────────────────────────────────────────────────────────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    print("[BROKER] Connecting to WiFi...")
    deadline = time.ticks_add(time.ticks_ms(), 20_000)
    while not wlan.isconnected():
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            raise RuntimeError("WiFi timeout")
        time.sleep(0.5)
    ip = wlan.ifconfig()[0]
    print(f"[BROKER] WiFi ready — IP: {ip}  (set this as BROKER_IP on all nodes)")
    return ip

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
                    sock.write(mk_publish(topic, payload, min(qos, sub_qos), retain))
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
    sock.write(bytes([T_CONNACK << 4, 2, 0, 0]))
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
        sock.write(bytes([T_PUBACK << 4, 2, pid >> 8, pid & 0xFF]))

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
                    sock.write(mk_publish(rt, rp, 0, True))
                except Exception:
                    pass

    sock.write(bytes([T_SUBACK << 4, 2 + len(granted),
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
            sock.write(bytes([T_PINGRESP << 4, 0]))
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
            led_a.on()
            print("[COORD] Cluster A root ONLINE")
        elif msg == 'offline':
            cluster_A['online'] = False
            led_a.off()
            print("[COORD] Cluster A root OFFLINE — triggering election")
            forward('csc2106/clusterA/election', b'ELECT', qos=1)

    # ── Root B health ──────────────────────────────────────────────────────────
    elif topic == 'csc2106/devB/status':
        if msg == 'online':
            cluster_B['online'] = True
            led_b.on()
            print("[COORD] Cluster B root ONLINE")
        elif msg == 'offline':
            cluster_B['online'] = False
            led_b.off()
            print("[COORD] Cluster B root OFFLINE — triggering election")
            forward('csc2106/clusterB/election', b'ELECT', qos=1)

    # ── Election results ───────────────────────────────────────────────────────
    elif topic == 'csc2106/clusterA/elected':
        cluster_A.update(root=msg, online=True)
        led_a.on()
        retained['csc2106/clusterA/root'] = payload
        print(f"[COORD] Cluster A new root elected: {msg}")
        forward('csc2106/clusterA/root', payload, retain=True)

    elif topic == 'csc2106/clusterB/elected':
        cluster_B.update(root=msg, online=True)
        led_b.on()
        retained['csc2106/clusterB/root'] = payload
        print(f"[COORD] Cluster B new root elected: {msg}")
        forward('csc2106/clusterB/root', payload, retain=True)

    # ── Cross-cluster routing  A → B ──────────────────────────────────────────
    # Node in cluster A publishes to:  csc2106/clusterA/to/clusterB/<subtopic>
    # Broker relays to current B root: csc2106/<rootB>/relay/<subtopic>
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

# ── Main ───────────────────────────────────────────────────────────────────────
connect_wifi()

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('', PORT))
srv.listen(MAX_CLIENTS)
srv.setblocking(False)

poll = uselect.poll()
poll.register(srv, uselect.POLLIN)

print(f"[BROKER] Listening on port {PORT}  —  max {MAX_CLIENTS} clients")

blink_state = False
last_blink  = time.ticks_ms()

while True:
    events = poll.poll(50)   # 50 ms timeout keeps the blink responsive

    for obj, ev in events:

        # ── Accept new connection ──────────────────────────────────────────────
        if obj is srv:
            try:
                conn, addr = srv.accept()
                conn.setblocking(False)
                buffers[conn] = bytearray()
                poll.register(conn, uselect.POLLIN)
                print(f"[BROKER] New connection from {addr[0]}:{addr[1]}")
            except Exception as e:
                print("[BROKER] accept error:", e)

        # ── Data from an existing client ───────────────────────────────────────
        else:
            sock = obj
            try:
                data = sock.read(512)
            except OSError:
                data = None

            if data is None:
                continue      # EAGAIN — no data despite POLLIN (spurious wake-up)

            if not data:
                # Empty read = connection closed by peer
                close_sock(sock)
                try:
                    poll.unregister(sock)
                except Exception:
                    pass
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
                        poll.unregister(sock)
                    except Exception:
                        pass
                    # close_sock already called if it was a DISCONNECT;
                    # call it again harmlessly (no-op if already removed)
                    close_sock(sock)
                    break

    # ── Heartbeat blink (onboard LED) ─────────────────────────────────────────
    now = time.ticks_ms()
    if time.ticks_diff(now, last_blink) >= 500:
        blink_state = not blink_state
        led_board.value(blink_state)
        last_blink = now
