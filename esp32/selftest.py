# Wiring check. Upload as main.py before the real firmware to confirm your
# LEDs and pins: it cycles red -> yellow -> green -> all -> off forever.
#   python3 push.py selftest.py /dev/ttyUSB0
import time
from machine import Pin

PIN_RED, PIN_YELLOW, PIN_GREEN = 25, 26, 27
COMMON_ANODE = False
ON, OFF = (0, 1) if COMMON_ANODE else (1, 0)

R = Pin(PIN_RED, Pin.OUT); Y = Pin(PIN_YELLOW, Pin.OUT); G = Pin(PIN_GREEN, Pin.OUT)
def rgb(r, y, g):
    R.value(r); Y.value(y); G.value(g)

while True:
    rgb(ON, OFF, OFF); time.sleep(0.6)   # red
    rgb(OFF, ON, OFF); time.sleep(0.6)   # yellow
    rgb(OFF, OFF, ON); time.sleep(0.6)   # green
    rgb(ON, ON, ON);   time.sleep(0.6)   # all
    rgb(OFF, OFF, OFF); time.sleep(0.6)  # off
