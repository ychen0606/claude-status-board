# ES3C28P 固件笔记（Claude 状态看板）

LCDWIKI ES3C28P：ESP32-S3 + 2.8" ILI9341V 240×320 + FT6336G 电容触摸 + RGB灯 + 喇叭/麦克风/SD。

## 引脚（官方规格书 V1.0）

| 设备 | 引脚 |
|------|------|
| LCD (ILI9341V, SPI) | CS=10, DC=46, SCK=12, MOSI=11, MISO=13, RST=芯片复位, 背光BL=45 |
| 触摸 (FT6336G, I2C @0x38) | SDA=16, SCL=15, RST=18, INT=17 |
| RGB 三色灯 | GPIO42（WS2812 单线时序） |
| 喇叭/音频 (I2S) | 功放EN=1(低有效), MCLK=4, BCLK=5, DOUT=6, LRCLK=7, DIN=8；音频codec I2C 与触摸共用(SDA16/SCL15) |
| 麦克风 | 走上面的 I2S DIN=8 |
| MicroSD (SDIO) | CLK=38, CMD=40, D0=39, D1=41, D2=48, D3=47 |
| 电池 ADC | GPIO9 |
| 按键 | BOOT=IO0, RESET=芯片复位 |
| 空闲扩展 IO | 2, 3, 14, 21 |

## Arduino IDE 设置

- 开发板：**ESP32S3 Dev Module**
- PSRAM：**OPI PSRAM**
- Flash Size：**16MB (128Mb)**
- USB CDC On Boot：Enabled（用 USB 口看串口日志方便）
- 库（库管理器装）：**LovyanGFX**、**ArduinoJson (v7)**、**Adafruit NeoPixel**

## 烧录

1. Type-C 连电脑。烧不进就按住 BOOT 再按一下 RESET 进下载模式。
2. 选对端口，点上传。
3. 上传前把 .ino 顶部的 `WIFI_SSID / WIFI_PASS` 填上。

## 到货后可能要调的点（都在 .ino 顶部或 setup 里）

- **颜色不对**（红蓝反）→ LGFX panel 配置里 `c.rgb_order = true;`
- **方向不对** → `lcd.setRotation(0..3)`
- **触摸位置偏/反** → Touch 配置 `offset_rotation`，或交换/翻转 x/y
- **屏发白/不亮** → 背光 `pin_bl=45`、`setBrightness()`；或 SPI 频率 `freq_write` 调低到 27MHz
- **触摸无反应** → 确认 GPIO18 复位已放开（setup 里有），I2C 地址 0x38

## 还没做（先把屏跑通再加）

- 蜂鸣提示音：要配 I2S + 音频 codec（和小智同款，codec 在 I2C 上），待定。
- 喇叭口要插喇叭才出声。
