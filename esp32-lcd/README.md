# ESP32 touch-LCD board firmware

Thin client for the server-rendered board: it pulls `/board.png` over WiFi, blits it, and sends touch hits back via the hitboxes in `/board.json`. All UI lives on the server (`board_render.py`) — you rarely reflash.

## Hardware

LCDWIKI **ES3C28P**: ESP32-S3 + 2.8" **ILI9341V** 240×320 SPI (IPS) + **FT6336** capacitive touch (I2C `0x38`) + a WS2812 RGB LED on GPIO42. Pins are baked into the `LGFX` class in the sketch (from the ES3C28P V1.0 datasheet).

## Build & flash (arduino-cli)

```sh
arduino-cli config add board_manager.additional_urls \
  https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32
arduino-cli lib install "LovyanGFX" "ArduinoJson" "Adafruit NeoPixel" "WiFiManager"

# edit the top of claude_board_es3c28p.ino: HOST = your server's IP
FQBN="esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi,PartitionScheme=app3M_fat9M_16MB"
arduino-cli compile -b "$FQBN" --output-dir build claude_board_es3c28p
arduino-cli upload -p /dev/ttyACM0 -b "$FQBN" --input-dir build
```

The board enumerates as native USB (`/dev/ttyACM0`). If upload fails with "Check if ESP connected", the USB data link dropped — unplug/replug.

## First boot

1. **Touch calibration** — tap the 4 corner arrows once; the values are saved to NVS and never asked again (hold a finger on the screen at boot to recalibrate).
2. **WiFi** — joins your saved network, or opens a captive-portal AP `ClaudeBoard-Setup` (browse to `192.168.4.1`) if it can't. Hold the **BOOT** button at power-on, or tap the gear in the UI, to reconfigure WiFi later.

## OTA updates

After the first USB flash, push firmware over WiFi (no cable):

```sh
python3 "$(find ~/.arduino15/packages/esp32 -name espota.py | head -1)" \
  -i <board-ip> -p 3232 -f build/claude_board_es3c28p.ino.bin
```

## Panel note: `invert=true`

This IPS ILI9341V panel displays **inverted** colors. The sketch sets `c.invert = true;` in the `LGFX` config to fix it (without it, red shows as cyan, white as black). If your panel's colors are swapped, toggle that first; `rgb_order` only swaps red↔blue.
