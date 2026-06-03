#!/usr/bin/env python3
# Upload a local .py file to a MicroPython board as main.py over the serial
# REPL (no mpremote needed), then soft-reboot so it runs.
#
#   python3 push.py main.py [/dev/ttyUSB0]
#
# Needs pyserial:  pip install pyserial
import serial, time, sys

src = open(sys.argv[1]).read()
port = sys.argv[2] if len(sys.argv) > 2 else "/dev/ttyUSB0"

s = serial.Serial(port, 115200, timeout=2)
s.write(b"\r\x03\x03"); time.sleep(0.3); s.read(20000)      # interrupt running program
s.write(b"\x01"); time.sleep(0.3); s.read(20000)            # enter raw REPL
s.write(("f=open('main.py','w');f.write(%r);f.close()\r" % src).encode())
s.write(b"\x04"); time.sleep(1.2)                           # execute the write
print("write:", s.read(20000)[-80:])
s.write(b"\x02"); time.sleep(0.3)                           # leave raw REPL
s.write(b"\x04"); time.sleep(0.8)                           # soft reboot -> run main.py
print("boot:", s.read(20000)[-160:])
s.close()
