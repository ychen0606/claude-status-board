// Claude 状态看板 —— ES3C28P (ESP32-S3 + 2.8" ILI9341V 240x320 + FT6336 触摸 + RGB灯)
// 瘦客户端: UI 由服务端渲染成 PNG, 板子只负责拉图显示 + 处理触摸。
//   GET /board.json?view=&req=  -> {hash, led, buttons:[{x,y,w,h,act,req}]}
//   GET /board.png?view=&req=   -> 当前界面的 PNG(240x320)
//   触摸命中 buttons -> open(进批准)/approve/deny(/decide)/back; 改 view&req 后强制刷新。
// 库: LovyanGFX、ArduinoJson(v7)、Adafruit NeoPixel。板: ESP32S3 / OPI PSRAM / 16MB。

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <math.h>
#include <Preferences.h>
#include <WiFiManager.h>
#include <ArduinoOTA.h>
#define LGFX_USE_V1
#include <LovyanGFX.hpp>

// ======================= 用户配置 =======================
static const char* WIFI_SSID = "你的WiFi名";
static const char* WIFI_PASS = "你的WiFi密码";
static const char* HOST      = "192.168.1.50";
static const int   PORT      = 8088;
// =======================================================

#define RGB_PIN 42
Adafruit_NeoPixel rgb(1, RGB_PIN, NEO_GRB + NEO_KHZ800);

class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ILI9341 _panel;
  lgfx::Bus_SPI       _bus;
  lgfx::Light_PWM     _light;
  lgfx::Touch_FT5x06  _touch;
public:
  LGFX() {
    { auto c = _bus.config();
      c.spi_host = SPI2_HOST; c.spi_mode = 0;
      c.freq_write = 40000000; c.freq_read = 16000000;
      c.spi_3wire = false; c.use_lock = true; c.dma_channel = SPI_DMA_CH_AUTO;
      c.pin_sclk = 12; c.pin_mosi = 11; c.pin_miso = 13; c.pin_dc = 46;
      _bus.config(c); _panel.setBus(&_bus);
    }
    { auto c = _panel.config();
      c.pin_cs = 10; c.pin_rst = -1; c.pin_busy = -1;
      c.panel_width = 240; c.panel_height = 320;
      c.offset_x = 0; c.offset_y = 0; c.offset_rotation = 0;
      c.readable = true; c.invert = true;          // IPS ILI9341V 需反色(INVON), 否则整屏反色
      c.rgb_order = false; c.dlen_16bit = false; c.bus_shared = false;
      _panel.config(c);
    }
    { auto c = _light.config();
      c.pin_bl = 45; c.invert = false; c.freq = 44100; c.pwm_channel = 7;
      _light.config(c); _panel.setLight(&_light);
    }
    { auto c = _touch.config();
      c.x_min = 0; c.x_max = 239; c.y_min = 0; c.y_max = 319;
      c.pin_int = 17; c.pin_sda = 16; c.pin_scl = 15;
      c.i2c_port = 0; c.i2c_addr = 0x38; c.freq = 400000;
      c.bus_shared = false; c.offset_rotation = 0;
      _touch.config(c); _panel.setTouch(&_touch);
    }
    setPanel(&_panel);
  }
};
LGFX lcd;
#define TOUCH_RST 18

struct Btn { int x, y, w, h; String act, req; };
static const int MAXBTN = 10;
Btn g_btn[MAXBTN]; int g_nbtn = 0;

String g_view = "list", g_req = "", g_hash = "", g_led = "off";
bool g_online = false;
bool g_wasAlert = false;          // 上一轮是否处于授权告警(用于检测"新授权")
bool g_wasDone = false;           // 上一轮是否完成态(用于检测"刚完成")
int  g_failCount = 0;             // 连续拉取失败次数(扛过瞬时网络抖动)
int  g_bright = 160;              // 服务端建议背光亮度
uint8_t* g_img = nullptr;
static const int IMG_MAX = 90000;
uint32_t lastPoll = 0, lastTouch = 0;
Preferences prefs;

void setRGB(uint8_t r, uint8_t g, uint8_t b){ rgb.setPixelColor(0, rgb.Color(r,g,b)); rgb.show(); }
String base() { return String("http://") + HOST + ":" + PORT; }

static const char* AP_NAME = "ClaudeBoard-Setup";

void portalDraw() {                 // 配网门户启动时画在屏上
  lcd.setBrightness(200);
  lcd.fillScreen(lcd.color565(13,15,20));
  lcd.setFont(&fonts::efontCN_16); lcd.setTextColor(lcd.color565(96,160,250));
  lcd.setCursor(14, 22); lcd.print("配 网 模 式");
  lcd.setFont(&fonts::efontCN_14); lcd.setTextColor(0xFFFF);
  lcd.setCursor(14, 64);  lcd.print("1. 手机连 WiFi:");
  lcd.setTextColor(lcd.color565(70,211,110)); lcd.setCursor(30, 90); lcd.print(AP_NAME);
  lcd.setTextColor(0xFFFF); lcd.setCursor(14, 126); lcd.print("2. 浏览器打开:");
  lcd.setTextColor(lcd.color565(70,211,110)); lcd.setCursor(30, 152); lcd.print("192.168.4.1");
  lcd.setTextColor(0xFFFF);
  lcd.setCursor(14, 188); lcd.print("3. 选你的 WiFi、输密码、保存");
  lcd.setTextColor(lcd.color565(139,152,164));
  lcd.setCursor(14, 224); lcd.print("完成后板子自动重连");
  lcd.setCursor(14, 250); lcd.print("(超时 3 分钟)");
}

// 连网: 默认连出厂网; 连不上或 forceCfg -> 开配网门户。creds 由 WiFiManager 存 NVS。
void runWifi(bool forceCfg) {
  WiFi.mode(WIFI_STA); WiFi.setSleep(false);
  // 首次(NVS 无网络)预置出厂网, 当前网络开箱即用; 换网时门户里改
  if (WiFi.SSID().length() == 0) { WiFi.persistent(true); WiFi.begin(WIFI_SSID, WIFI_PASS); delay(150); }
  lcd.fillScreen(lcd.color565(13,15,20));
  lcd.setFont(&fonts::efontCN_16); lcd.setTextColor(0xFFFF);
  lcd.setCursor(14, 150); lcd.print(forceCfg ? "进入配网…" : "WiFi 连接中…");
  WiFiManager wm;
  wm.setConfigPortalTimeout(180);
  wm.setAPCallback([](WiFiManager*){ portalDraw(); });
  bool ok = forceCfg ? wm.startConfigPortal(AP_NAME) : wm.autoConnect(AP_NAME);
  WiFi.setAutoReconnect(true);
  Serial.printf("[wifi] %s ip=%s ssid=%s\n", ok ? "ok" : "fail",
                WiFi.localIP().toString().c_str(), WiFi.SSID().c_str());
}

bool fetchJson(String& hashOut) {
  HTTPClient http;
  http.begin(base() + "/board.json?view=" + g_view + "&req=" + g_req);
  http.setConnectTimeout(1500); http.setTimeout(2500);
  int code = http.GET();
  if (code != 200) { http.end(); return false; }
  String body = http.getString(); http.end();
  JsonDocument doc;
  if (deserializeJson(doc, body)) return false;
  hashOut = String((const char*)(doc["hash"] | ""));
  g_led   = String((const char*)(doc["led"]  | "off"));
  g_bright = doc["bright"] | 160;
  g_nbtn = 0;
  for (JsonObject b : doc["buttons"].as<JsonArray>()) {
    if (g_nbtn >= MAXBTN) break;
    g_btn[g_nbtn].x = b["x"] | 0; g_btn[g_nbtn].y = b["y"] | 0;
    g_btn[g_nbtn].w = b["w"] | 0; g_btn[g_nbtn].h = b["h"] | 0;
    g_btn[g_nbtn].act = String((const char*)(b["act"] | ""));
    g_btn[g_nbtn].req = String((const char*)(b["req"] | ""));
    g_nbtn++;
  }
  return true;
}

bool fetchPng() {
  HTTPClient http;
  http.begin(base() + "/board.png?view=" + g_view + "&req=" + g_req);
  http.setConnectTimeout(2000); http.setTimeout(4000);
  int code = http.GET();
  if (code != 200) { http.end(); return false; }
  int total = http.getSize();
  WiFiClient* st = http.getStreamPtr();
  int idx = 0; uint32_t t0 = millis();
  while (millis() - t0 < 5000) {
    size_t av = st->available();
    if (av) {
      int r = st->readBytes(g_img + idx, av < (size_t)(IMG_MAX - idx) ? av : (size_t)(IMG_MAX - idx));
      idx += r; t0 = millis();
      if (idx >= IMG_MAX) break;
    } else if (!http.connected()) {
      break;
    } else delay(2);
    if (total > 0 && idx >= total) break;
  }
  http.end();
  if (idx < 100) return false;
  lcd.drawPng(g_img, idx, 0, 0);
  return true;
}

void sendDecision(const String& req, const char* d) {
  HTTPClient http;
  http.begin(base() + "/decide?d=" + d + "&req=" + req);
  http.setConnectTimeout(1200); http.setTimeout(1500);
  http.GET(); http.end();
}

void drawOffline() {
  lcd.fillScreen(lcd.color565(13,15,20));
  lcd.setFont(&fonts::efontCN_16); lcd.setTextColor(lcd.color565(245,184,64));
  lcd.setCursor(34, 150); lcd.print("离线 · 连不上看板");
}

void applyLED() {
  if (!g_online) { setRGB(20, 8, 0); return; }
  if (g_led == "alert") {                       // 需授权: 红色心跳
    float p = sinf(millis() / 320.0f) * 0.5f + 0.5f;
    setRGB(8 + (int)(72 * p), 0, 0);
  } else if (g_led == "done") {                      // 刚完成: 绿色呼吸
    float p = sinf(millis() / 350.0f) * 0.5f + 0.5f;
    setRGB(0, 20 + (int)(40 * p), 8);
  } else if (g_led == "work") setRGB(0, 36, 0);
  else if (g_led == "idle")   setRGB(2, 2, 2);
  else                        setRGB(0, 0, 0);
}

void applyBacklight() {
  static int cur = -2;
  static uint32_t lastSet = 0;
  int target;
  if (!g_online)                      target = 150;
  else if (g_led == "alert")          target = 235;       // 授权: 屏常亮(卡片自身脉动)
  else if (g_led == "done")           target = 210;       // 刚完成: 亮屏提醒
  else if (millis() - lastTouch < 8000) target = 210;     // 触摸唤醒 8s
  else                                target = g_bright;  // 服务端: 空闲/夜间自动暗
  if (target != cur && millis() - lastSet > 25) {         // 限频, 平滑
    lcd.setBrightness(target); cur = target; lastSet = millis();
  }
}

void flashScreen3() {                 // 新授权: 全屏红闪 3 下(强提醒)
  lcd.setBrightness(245);
  for (int i = 0; i < 3; i++) {
    lcd.fillScreen(lcd.color565(255, 45, 50)); delay(110);
    lcd.fillScreen(lcd.color565(13, 15, 20));  delay(110);
  }
}

void flashDone() {                    // 会话完成: 绿闪 2 下(温和提醒)
  lcd.setBrightness(235);
  for (int i = 0; i < 2; i++) {
    lcd.fillScreen(lcd.color565(40, 180, 90)); delay(120);
    lcd.fillScreen(lcd.color565(13, 15, 20));  delay(120);
  }
}

void pulseCards() {                   // 待授权卡片: 红色脉动描边(持续提醒)
  if (g_view != "list" || g_led != "alert") return;
  float p = sinf(millis() / 200.0f) * 0.5f + 0.5f;
  uint16_t col = lcd.color565(120 + (int)(135 * p), 22, 26);
  for (int i = 0; i < g_nbtn; i++) {
    if (g_btn[i].act == "open" || g_btn[i].act == "alert") {   // 可批准 或 仅提醒 的卡片都脉动
      Btn& b = g_btn[i];
      lcd.drawRoundRect(b.x, b.y, b.w, b.h, 8, col);
      lcd.drawRoundRect(b.x + 1, b.y + 1, b.w - 2, b.h - 2, 7, col);
    }
  }
}

void setup() {
  Serial.begin(115200); delay(200);
  Serial.println("\n[boot] claude_board thin-client");
  pinMode(TOUCH_RST, OUTPUT);
  digitalWrite(TOUCH_RST, LOW); delay(10); digitalWrite(TOUCH_RST, HIGH); delay(200);
  rgb.begin(); rgb.setBrightness(45); setRGB(0, 0, 20);

  g_img = (uint8_t*)ps_malloc(IMG_MAX);
  if (!g_img) g_img = (uint8_t*)malloc(IMG_MAX);

  lcd.init();
  lcd.setRotation(2);
  lcd.setBrightness(160);

  // 触摸校准: 存在 NVS, 只校一次。已存且开机时没按住屏幕 -> 直接加载; 否则点 4 角校准并保存。
  prefs.begin("board", false);
  {
    uint16_t cal[8];
    bool haveCal = (prefs.getBytes("calib", cal, sizeof(cal)) == sizeof(cal));
    int32_t hx, hy;
    bool held = lcd.getTouch(&hx, &hy);     // 开机按住屏幕 = 强制重新校准
    if (haveCal && !held) {
      lcd.setTouchCalibrate(cal);
      Serial.println("[calib] loaded from NVS");
    } else {
      lcd.fillScreen(0x0000);
      lcd.setTextColor(0xFFFF, 0x0000);
      lcd.setFont(&fonts::efontCN_16);
      lcd.setCursor(18, 140); lcd.print("依次点亮起的 4 个角");
      lcd.setCursor(18, 168); lcd.print("(只需校准这一次)");
      lcd.calibrateTouch(cal, 0xFFFF, 0x0000, 35);
      prefs.putBytes("calib", cal, sizeof(cal));
      Serial.printf("[calib] saved {%u,%u,%u,%u,%u,%u,%u,%u}\n",
                    cal[0],cal[1],cal[2],cal[3],cal[4],cal[5],cal[6],cal[7]);
    }
  }

  pinMode(0, INPUT_PULLUP);                    // BOOT 键
  bool forceCfg = (digitalRead(0) == LOW);     // 开机按住 BOOT = 强制进配网门户
  runWifi(forceCfg);
  if (WiFi.status() == WL_CONNECTED) {         // OTA: 以后走 WiFi 升级, 不用插 USB
    ArduinoOTA.setHostname("claudeboard");
    ArduinoOTA.begin();
    Serial.printf("[ota] ready ip=%s\n", WiFi.localIP().toString().c_str());
  }
  g_hash = "";
}

void loop() {
  ArduinoOTA.handle();                          // WiFi OTA 升级监听
  // 触摸 -> 命中服务端给的按钮
  int32_t tx, ty;
  if (lcd.getTouch(&tx, &ty) && millis() - lastTouch > 250) {
    lastTouch = millis();
    Serial.printf("[touch] (%ld,%ld)\n", (long)tx, (long)ty);
    for (int i = 0; i < g_nbtn; i++) {
      Btn& b = g_btn[i];
      if (tx >= b.x && tx <= b.x + b.w && ty >= b.y && ty <= b.y + b.h) {
        if (b.act == "open")      { g_view = "approve"; g_req = b.req; g_hash = ""; }
        else if (b.act == "approve" || b.act == "deny") {
          sendDecision(b.req, b.act.c_str()); g_view = "list"; g_req = ""; g_hash = "";
        } else if (b.act == "back") { g_view = "list"; g_req = ""; g_hash = ""; }
        else if (b.act == "detail") { g_view = "detail"; g_req = b.req; g_hash = ""; }
        else if (b.act == "wifi")  { runWifi(true); g_view = "list"; g_req = ""; g_hash = ""; }
        break;
      }
    }
  }

  // 轮询(批准页降到 2.5s 减少阻塞)
  uint32_t gap = (g_view == "approve") ? 2500 : 1000;
  if (millis() - lastPoll >= gap) {
    lastPoll = millis();
    if (WiFi.status() != WL_CONNECTED) {        // 掉线: 显示离线 + 触发自动重连
      g_online = false;
      if (g_hash != "OFFLINE") { drawOffline(); g_hash = "OFFLINE"; }
      WiFi.reconnect();
      return;
    }
    String h;
    if (fetchJson(h)) {
      g_online = true; g_failCount = 0;
      bool nowAlert = (g_led == "alert");
      if (nowAlert && !g_wasAlert) { flashScreen3(); g_hash = ""; }   // 新授权出现: 全屏闪3下
      g_wasAlert = nowAlert;
      g_wasDone = (g_led == "done");   // 完成不再全屏闪绿(用户要求), 仅绿卡片+绿灯提示
      if (h != g_hash) { if (fetchPng()) g_hash = h; }
    } else {
      // 单次失败不立刻离线: 连续 4 次(~8-10s)失败才显示离线, 扛过瞬时网络抖动
      g_failCount++;
      if (g_failCount >= 4) {
        g_online = false;
        if (g_hash != "OFFLINE") { drawOffline(); g_hash = "OFFLINE"; }
      }
    }
  }

  applyLED();
  applyBacklight();
  pulseCards();
  delay(8);
}
