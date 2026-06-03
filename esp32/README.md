# ESP32 traffic-light client

A hardware version of the board. Instead of a tablet, a small ESP32 drives a
traffic light on your desk: it joins your WiFi, polls the same `/status`
endpoint that `server.py` already serves, and lights up to show what Claude
Code is doing across all your sessions. Nothing to keep open, just a light you
glance at.

Runs on a plain ESP32 (ESP32-WROOM / DevKit) with MicroPython. Once flashed it
needs only USB power, so any phone charger works.

## States

The light is PWM-animated (gamma-corrected so the fades look smooth) and
crossfades when the state changes:

- green, breathing — running
- yellow, soft breathing — waiting for your next message; fades out after 3
  minutes so it isn't glowing all night (`SLEEP_AFTER_MS`), and comes back the
  moment Claude does anything
- red, heartbeat — paused on a permission prompt, waiting for you
- off — no active session
- red/yellow wig-wag — WiFi is down or the server can't be reached

This splits the board's single "red — waiting on you" into red (a permission
prompt) and yellow (just waiting for your next message).

On power-up it sweeps red → yellow → green once, and runs a comet sweep while
joining WiFi. Effect timing and brightness live in the tuning block at the top
of `main.py` (`GAMMA`, `*_BREATHE_S`, `HEART_S`, `TRANS_S`); drop `GAMMA` toward
1.8 or raise the floors if your LEDs look dim.

## Wiring

A 4-pin traffic-light module, or three discrete LEDs each with a current-limiting
resistor:

| module / LED | ESP32  |
|--------------|--------|
| red          | GPIO25 |
| yellow       | GPIO26 |
| green        | GPIO27 |
| common       | GND    |

That assumes a common-cathode module (the 4th pin is GND, drive a colour high to
light it). If yours is common anode (4th pin to 3V3), connect the common pin to
3V3 instead and set `COMMON_ANODE = True` in `main.py` and `selftest.py`.

GPIO 25/26/27 are clean output pins next to each other and clear of the boot
strapping pins; change them in the config block if you wired differently.

## Flashing

1. Put MicroPython on the board. Grab a build from
   <https://micropython.org/download/ESP32_GENERIC/>, then:

   ```
   pip install esptool
   esptool --chip esp32 -p /dev/ttyUSB0 erase_flash
   esptool --chip esp32 -p /dev/ttyUSB0 write_flash -z 0x1000 ESP32_GENERIC-*.bin
   ```

   `erase_flash` matters: skip it and a stale filesystem can leave MicroPython
   unable to mount its own storage. If `erase_flash` fails with a missing stub
   file, the esptool packaged by your distro is incomplete — install it from
   pip instead.

2. (Optional) Check the wiring first. Upload `selftest.py`, which cycles the
   three colours so you can confirm each one:

   ```
   python3 push.py selftest.py /dev/ttyUSB0
   ```

3. Edit the CONFIG block at the top of `main.py` — WiFi name/password and the
   IP and port of the host running `server.py` — then upload it:

   ```
   python3 push.py main.py /dev/ttyUSB0
   ```

   `push.py` writes the file over the serial REPL (no mpremote needed) and
   reboots. From then on `main.py` runs on power-up and reconnects WiFi on its
   own.

## Reaching the server

The ESP32 needs to reach the host running `server.py`. On the same LAN that
works out of the box. Across networks, put the host on Tailscale (or any
tunnel) and point `STATUS_HOST` at an address the ESP32's network can route to.
