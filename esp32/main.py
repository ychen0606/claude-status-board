# Claude Status Board - ESP32 traffic-light client (MicroPython)
#
# Connects to WiFi, polls the board server's /status endpoint, and drives a
# small traffic light so you can tell from across the room what Claude Code is
# doing. A hardware alternative to the tablet board - no browser, just a light.
#
# Runs on a plain ESP32 (ESP32-WROOM / DevKit). Flash MicroPython, edit the
# CONFIG block below, then upload this file as main.py with push.py. See
# README.md for wiring and flashing.

import network, time, json, socket
from machine import Pin

# ----------------------------- CONFIG -----------------------------
WIFI_SSID   = "your-2.4GHz-ssid"     # ESP32 classic is 2.4 GHz only
WIFI_PASS   = "your-wifi-password"
STATUS_HOST = "192.168.1.50"         # IP of the host running server.py
STATUS_PORT = 8088
POLL_S         = 2.0                  # how often to poll /status, seconds
SLEEP_AFTER_MS = 180000              # blank the light after waiting this long (3 min)

PIN_RED, PIN_YELLOW, PIN_GREEN = 25, 26, 27
COMMON_ANODE = False                 # True if the module's common pin goes to 3V3
# ------------------------------------------------------------------

ON, OFF = (0, 1) if COMMON_ANODE else (1, 0)
R = Pin(PIN_RED, Pin.OUT); Y = Pin(PIN_YELLOW, Pin.OUT); G = Pin(PIN_GREEN, Pin.OUT)
def rgb(r, y, g):
    R.value(r); Y.value(y); G.value(g)
rgb(OFF, OFF, OFF)

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

def wifi_connect():
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(60):
            if wlan.isconnected():
                break
            Y.value(ON); time.sleep(0.1); Y.value(OFF); time.sleep(0.15)
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

blink = False
def warn():     # red/yellow alternate = WiFi down or server unreachable
    global blink
    blink = not blink
    rgb(ON if blink else OFF, OFF if blink else ON, OFF)

last = None
last_active = time.ticks_ms()        # last time a session was working / needed you
wifi_connect()
while True:
    if not wlan.isconnected():
        if not wifi_connect():
            warn(); time.sleep(0.3); continue
    try:
        st = fetch_state()
    except Exception as e:
        print("ERR", e); st = None
    if st != last:
        print("STATE", st); last = st
    if st in ("working", "attention"):
        last_active = time.ticks_ms()

    if st is None:                                   # unreachable
        for _ in range(4):
            warn(); time.sleep(0.3)
    elif st == "attention":                          # red blink, never sleeps
        for _ in range(5):
            blink = not blink
            rgb(ON if blink else OFF, OFF, OFF); time.sleep(0.4)
    elif st == "working":                            # green solid
        rgb(OFF, OFF, ON); time.sleep(POLL_S)
    elif st == "input":                              # yellow solid, sleeps after 3 min
        awake = time.ticks_diff(time.ticks_ms(), last_active) < SLEEP_AFTER_MS
        rgb(OFF, ON if awake else OFF, OFF); time.sleep(POLL_S)
    else:                                            # off
        rgb(OFF, OFF, OFF); time.sleep(POLL_S)
