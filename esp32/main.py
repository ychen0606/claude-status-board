# Claude Status Board - ESP32 traffic-light client (MicroPython)
#
# Connects to WiFi, polls the board server's /status endpoint, and drives a
# small traffic light so you can tell from across the room what Claude Code is
# doing. A hardware alternative to the tablet board - no browser, just a light.
#
# The light is PWM-animated: gamma-corrected breathing, crossfades between
# states, a heartbeat for "waiting on you", and a sweep on power-up. Runs on a
# plain ESP32 (ESP32-WROOM / DevKit). Flash MicroPython, edit the CONFIG block,
# then upload this as main.py with push.py. See README.md.

import network, time, json, socket, math
from machine import Pin, PWM

# ----------------------------- CONFIG -----------------------------
WIFI_SSID   = "your-2.4GHz-ssid"     # ESP32 classic is 2.4 GHz only
WIFI_PASS   = "your-wifi-password"
STATUS_HOST = "192.168.1.50"         # IP of the host running server.py
STATUS_PORT = 8088
POLL_S         = 2.0                  # how often to poll /status, seconds
SLEEP_AFTER_MS = 180000              # blank the light after waiting this long (3 min)

PIN_RED, PIN_YELLOW, PIN_GREEN = 25, 26, 27
COMMON_ANODE = False                 # True if the module's common pin goes to 3V3

# effect tuning
GAMMA            = 2.2                # perceptual brightness; higher = silkier breathing
GREEN_BREATHE_S  = 3.0               # working breathe period
GREEN_FLOOR      = 0.18              # working never fades fully dark
YELLOW_BREATHE_S = 3.8               # waiting-for-input breathe period
YELLOW_MAX       = 0.85
HEART_S          = 1.1               # red heartbeat (permission) period
TRANS_S          = 0.45             # crossfade time between states
DT               = 0.03             # frame interval (~33 fps)
# ------------------------------------------------------------------

MAXD = 65535
P = (PWM(Pin(PIN_RED), freq=1000, duty_u16=0),
     PWM(Pin(PIN_YELLOW), freq=1000, duty_u16=0),
     PWM(Pin(PIN_GREEN), freq=1000, duty_u16=0))

def setb(i, b):
    b = 0.0 if b < 0 else 1.0 if b > 1 else b
    d = int((b ** GAMMA) * MAXD)
    P[i].duty_u16(MAXD - d if COMMON_ANODE else d)

def show(r, y, g):
    setb(0, r); setb(1, y); setb(2, g)

def breathe(ph, period):
    return 0.5 - 0.5 * math.cos(2 * math.pi * (ph % period) / period)

def heartbeat(ph):                   # sharp double-thump, then a rest
    x = (ph % HEART_S) / HEART_S
    def pls(c, w):
        dd = x - c
        return math.exp(-(dd * dd) / (2 * w * w))
    return min(1.0, 0.05 + pls(0.05, 0.04) + pls(0.22, 0.04))

def smooth(x):
    return x * x * (3 - 2 * x)

def effect(st, ph, asleep):          # -> (r, y, g) target brightness 0..1
    if st == "working":
        return (0, 0, GREEN_FLOOR + (1 - GREEN_FLOOR) * breathe(ph, GREEN_BREATHE_S))
    if st == "input":
        return (0, 0, 0) if asleep else (0, YELLOW_MAX * breathe(ph, YELLOW_BREATHE_S), 0)
    if st == "attention":
        return (heartbeat(ph), 0, 0)
    if st == "unreachable":
        return (1, 0, 0) if (ph % 0.24) < 0.12 else (0, 0.9, 0)
    return (0, 0, 0)

def greet():                         # power-up sweep red -> yellow -> green
    for i in range(3):
        for k in range(14):
            show(*[(k / 13.0 if j == i else 0) for j in range(3)]); time.sleep(0.010)
        for k in range(14):
            show(*[(1 - k / 13.0 if j == i else 0) for j in range(3)]); time.sleep(0.010)
    show(0, 0, 0)

wlan = network.WLAN(network.STA_IF); wlan.active(True)

def wifi_connect():
    ph = 0.0
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(400):
            if wlan.isconnected():
                break
            pos = (ph % 0.9) / 0.3            # comet sweep while joining
            for i in range(3):
                setb(i, max(0.0, 0.9 - 0.9 * abs(i - pos)))
            ph += DT; time.sleep(DT)
    show(0, 0, 0)
    print("WIFI ok ip=", wlan.ifconfig()[0]) if wlan.isconnected() else print("WIFI fail")
    return wlan.isconnected()

def fetch_state():
    s = socket.socket(); s.settimeout(4)
    try:
        s.connect((STATUS_HOST, STATUS_PORT))
        s.send(("GET /status HTTP/1.0\r\nHost: %s\r\n\r\n" % STATUS_HOST).encode())
        buf = b""
        while True:
            d = s.recv(512)
            if not d:
                break
            buf += d
            if len(buf) > 6000:
                break
    finally:
        s.close()
    i = buf.find(b"\r\n\r\n")
    if i < 0:
        return None
    states = [x.get("state") for x in json.loads(buf[i + 4:]).get("slots", [])]
    if "attention" in states: return "attention"   # waiting on you (permission prompt)
    if "working"   in states: return "working"     # running
    if "idle"      in states: return "input"       # waiting for your next message
    return "off"                                    # no active session

ph = 0.0
disp = [0.0, 0.0, 0.0]
from_rgb = [0.0, 0.0, 0.0]
trans_t = 99.0
last = "boot"
last_active = time.ticks_ms()
greet()
wifi_connect()
while True:
    if not wlan.isconnected():
        if not wifi_connect():
            continue
    try:
        st = fetch_state()
    except Exception as e:
        print("ERR", e); st = None
    st_eff = "unreachable" if st is None else st
    if st in ("working", "attention"):
        last_active = time.ticks_ms()
    if st_eff != last:                               # start a crossfade into the new state
        print("STATE", st_eff)
        from_rgb = list(disp); trans_t = 0.0; last = st_eff

    for _ in range(int(POLL_S / DT)):
        asleep = (st_eff == "input" and time.ticks_diff(time.ticks_ms(), last_active) >= SLEEP_AFTER_MS)
        tgt = effect(st_eff, ph, asleep)
        if trans_t < TRANS_S:
            f = smooth(trans_t / TRANS_S)
            out = [from_rgb[k] + (tgt[k] - from_rgb[k]) * f for k in range(3)]
            trans_t += DT
        else:
            out = list(tgt)
        show(out[0], out[1], out[2]); disp = out
        ph += DT; time.sleep(DT)
