#include <Arduino.h>
#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include <DIYables_TFT_Touch_Shield.h>
#include <math.h>
#include <zephyr/devicetree.h>
#include <glcdfont.c>
#include "video_protocol.h"

// Fast TFT bus types; declared early so Arduino's generated prototypes can see them.
struct BusPin { uint32_t reg; uint8_t pin; };
struct BusByte { uint32_t w[2]; };  // BSRR words for the (up to) two data ports

#if !defined(ARDUINO_UNO_Q)
#error "Select Arduino UNO Q for this starter."
#endif

// Hosts select the controller fitted to their preassembled consoles.
#ifndef ARCADE_TFT_HX8357D
#define ARCADE_TFT_HX8357D 1
#endif
#if ARCADE_TFT_HX8357D
DIYables_TFT_HX8357D_Shield display;
#else
DIYables_TFT_RM68140_Shield display;
#endif

const uint8_t BUTTONS_ADDRESS = 0x3E;
const uint8_t JOYSTICK_ADDRESS = 0x2C;
ModulinoButtons buttons(BUTTONS_ADDRESS);
ModulinoMovement movement;
bool movementReady = false;

const uint16_t TFT_BLACK = 0x0000;
const uint16_t TFT_WHITE = 0xFFFF;
const uint16_t TFT_CYAN = 0x07FF;
unsigned long lastFrameAt = 0;
bool waiting = true;
int videoSession = 0;
int nextVideoSession = 0;
int lastX = -1;
int lastY = -1;
bool screenReset = true;  // The waiting screen replaced the game; Python must redraw.

bool readPacket(uint8_t address, uint8_t payload[3]) {
  // update() means "changed", not "read succeeded"; reject incomplete wire packets.
  int count = Wire1.requestFrom(address, (uint8_t)4);
  if (count != 4) {
    while (Wire1.available()) Wire1.read();
    return false;
  }
  Wire1.read();  // Modulino pinstrap address precedes the three input bytes.
  for (int i = 0; i < 3; ++i) payload[i] = Wire1.read();
  return true;
}

// Fills video, connected, buttons, x, y, ax, ay, az.
void sampleInputs(int v[8]) {
  uint8_t buttonData[3] = {};
  uint8_t stickData[3] = {};
  bool buttonsOk = readPacket(BUTTONS_ADDRESS, buttonData);
  bool joystickOk = readPacket(JOYSTICK_ADDRESS, stickData);
  bool movementOk = movementReady && movement.update();
  float ax = movementOk ? movement.getX() : 0;
  float ay = movementOk ? movement.getY() : 0;
  float az = movementOk ? movement.getZ() : 0;
  movementOk = movementOk && isfinite(ax) && isfinite(ay) && isfinite(az);
  int connected = (buttonsOk ? 1 : 0) | (joystickOk ? 2 : 0) | (movementOk ? 4 : 0);
  int pressed = 0;
  if (buttonsOk) {
    for (int i = 0; i < 3; ++i) if (buttonData[i]) pressed |= 1 << i;
    buttons.setLeds(buttonData[0], buttonData[1], buttonData[2]);
  }
  if (joystickOk && stickData[2]) pressed |= 8;
  v[0] = videoSession;
  v[1] = connected;
  v[2] = pressed;
  v[3] = joystickOk ? 128 - (int)stickData[0] : 0;
  v[4] = joystickOk ? 128 - (int)stickData[1] : 0;
  v[5] = movementOk ? (int)(constrain(ax, -16.0f, 16.0f) * 1000) : 0;
  v[6] = movementOk ? (int)(constrain(ay, -16.0f, 16.0f) * 1000) : 0;
  v[7] = movementOk ? (int)(constrain(az, -16.0f, 16.0f) * 1000) : 0;
}

String readInputs() {
  int v[8];
  sampleInputs(v);
  char json[180];
  snprintf(json, sizeof(json),
           "{\"video\":%d,\"connected\":%d,\"buttons\":%d,\"x\":%d,\"y\":%d,"
           "\"ax\":%d,\"ay\":%d,\"az\":%d}",
           v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
  return String(json);
}

void textLine(int y, const char* text) {
  display.setCursor(12, y);
  display.setTextColor(TFT_WHITE, TFT_BLACK);
  display.print(text);
}

void showWaiting() {
  if (videoSession) {
    videoSession = 0;
    display.fillScreen(TFT_BLACK);
    textLine(10, "UNO Q arcade starter");
    display.drawRect(12, 160, 456, 148, TFT_WHITE);
  }
  display.fillRect(12, 36, 456, 112, TFT_BLACK);
  textLine(36, "Waiting for App Lab...");
  if (lastX >= 0) display.fillCircle(lastX, lastY, 6, TFT_BLACK);
  lastX = -1;
  waiting = true;
  screenReset = true;
}

bool drawFrame(int x, int y, int pressed, int ax, int ay, int az, int connected) {
  if (videoSession) return false;  // RetroArch owns the display until release/timeout.
  // Bound every RPC input before using it for drawing or bit masks.
  x = constrain(x, 20, 460);
  y = constrain(y, 168, 300);
  pressed &= 15;
  connected &= 7;
  if (!(connected & 1)) pressed &= 8;
  if (!(connected & 2)) { pressed &= 7; x = 240; y = 234; }
  if (!(connected & 4)) { ax = 0; ay = 0; az = 0; }
  ax = constrain(ax, -16000, 16000);
  ay = constrain(ay, -16000, 16000);
  az = constrain(az, -16000, 16000);
  if (waiting) display.fillRect(12, 36, 456, 112, TFT_BLACK);
  char line[40];
  snprintf(line, sizeof(line), "Buttons:%s Stick:%s IMU:%s  ",
           connected & 1 ? "OK" : "--", connected & 2 ? "OK" : "--",
           connected & 4 ? "OK" : "--");
  textLine(36, line);
  snprintf(line, sizeof(line), "A:%d  B:%d  C:%d  Stick press:%d ",
           !!(pressed & 1), !!(pressed & 2), !!(pressed & 4), !!(pressed & 8));
  textLine(64, line);
  textLine(92, "Motion from neutral (mg)");
  snprintf(line, sizeof(line), "%6d / %6d / %6d   ", ax, ay, az);
  textLine(120, line);
  if (lastX >= 0) display.fillCircle(lastX, lastY, 6, TFT_BLACK);
  display.fillCircle(x, y, 6, pressed ? TFT_WHITE : TFT_CYAN);
  lastX = x;
  lastY = y;
  lastFrameAt = millis();
  waiting = false;
  return true;
}

int beginVideo() {
  if (videoSession) return 0;  // Only one stream may own the display.
  nextVideoSession = nextVideoSession == 2147483647 ? 1 : nextVideoSession + 1;
  videoSession = nextVideoSession;
  display.fillScreen(TFT_BLACK);
  textLine(10, "RetroArch / TFT bridge");
  textLine(294, "C + stick press: menu");
  lastX = -1;
  lastFrameAt = millis();
  waiting = false;
  return videoSession;
}

String pollVideo(int session) {
  if (!videoSession || session != videoSession) return String("");
  String inputs = readInputs();
  lastFrameAt = millis();
  return inputs;
}

String videoTile(int session, int tile, MsgPack::bin_t<uint8_t> data) {
  static uint16_t pixels[ArcadeVideo::TILE_PIXELS * 4];
  if (!videoSession || session != videoSession ||
      !ArcadeVideo::decode(tile, data.data(), data.size(), pixels)) return String("");
  display.drawRGBBitmap(80 + (tile % 10) * 32, 40 + (tile / 10) * 16, pixels, 32, 16);
  return pollVideo(session);  // Return fresh controls after each acknowledged tile.
}

bool endVideo(int session) {
  if (!videoSession || session != videoSession) return false;
  showWaiting();
  return true;
}

// ---- Level Devil drawing ---------------------------------------------------
// On UNO Q the DIYables library drives every bus bit with digitalWrite, so a
// full-screen fill takes seconds. The fast path writes the same shield pins
// through the GPIO set/reset registers; pins come from the board devicetree.
// Set ARCADE_FAST_TFT to 0 to draw through the library instead.
#ifndef ARCADE_FAST_TFT
#define ARCADE_FAST_TFT 1
#endif

#define ARCADE_PINS DT_PATH(zephyr_user)
#define PIN_REG(n) DT_REG_ADDR(DT_GPIO_CTLR_BY_IDX(ARCADE_PINS, digital_pin_gpios, n))
#define PIN_NUM(n) DT_GPIO_PIN_BY_IDX(ARCADE_PINS, digital_pin_gpios, n)

// Library defaults: data bits 0-7 on D8, D9, D2-D7; WR on A1, C/D on A2.
const BusPin BUS_DATA[8] = {{PIN_REG(8), PIN_NUM(8)}, {PIN_REG(9), PIN_NUM(9)},
                            {PIN_REG(2), PIN_NUM(2)}, {PIN_REG(3), PIN_NUM(3)},
                            {PIN_REG(4), PIN_NUM(4)}, {PIN_REG(5), PIN_NUM(5)},
                            {PIN_REG(6), PIN_NUM(6)}, {PIN_REG(7), PIN_NUM(7)}};
const BusPin BUS_WR = {PIN_REG(15), PIN_NUM(15)};
const BusPin BUS_CD = {PIN_REG(16), PIN_NUM(16)};
const uint32_t GPIO_OSPEEDR = 0x08, GPIO_ODR = 0x14, GPIO_BSRR = 0x18;

bool fastBus = false;
volatile uint32_t* dataBsrr[2];
uint8_t dataSide[8];
volatile uint32_t* wrBsrr;
volatile uint32_t* wrOdr;
volatile uint32_t* cdBsrr;

inline volatile uint32_t* gpioReg(uint32_t base, uint32_t offset) {
  return (volatile uint32_t*)(base + offset);
}

bool fastBusBegin() {
  uint32_t ports[2] = {};
  int count = 0;
  for (int i = 0; i < 8; ++i) {
    int side = 0;
    while (side < count && ports[side] != BUS_DATA[i].reg) ++side;
    if (side == count) {
      if (count == 2) return false;  // Unexpected wiring: keep the library path.
      ports[count++] = BUS_DATA[i].reg;
    }
    dataSide[i] = side;
  }
  if (count == 1) ports[1] = ports[0];
  for (int i = 0; i < 2; ++i) dataBsrr[i] = gpioReg(ports[i], GPIO_BSRR);
  wrBsrr = gpioReg(BUS_WR.reg, GPIO_BSRR);
  wrOdr = gpioReg(BUS_WR.reg, GPIO_ODR);
  cdBsrr = gpioReg(BUS_CD.reg, GPIO_BSRR);
  // Faster output edges on the bus pins (OSPEEDR "high").
  BusPin pins[10] = {BUS_DATA[0], BUS_DATA[1], BUS_DATA[2], BUS_DATA[3], BUS_DATA[4],
                     BUS_DATA[5], BUS_DATA[6], BUS_DATA[7], BUS_WR, BUS_CD};
  for (const BusPin& p : pins) {
    volatile uint32_t* speed = gpioReg(p.reg, GPIO_OSPEEDR);
    *speed = (*speed & ~(3u << (2 * p.pin))) | (2u << (2 * p.pin));
  }
  return true;
}

BusByte busEncode(uint8_t v) {
  BusByte b = {{0, 0}};
  for (int i = 0; i < 8; ++i) {
    uint8_t pin = BUS_DATA[i].pin;
    b.w[dataSide[i]] |= (v >> i & 1) ? 1u << pin : 1u << (pin + 16);
  }
  return b;
}

inline void busWrite(const BusByte& b) {
  *dataBsrr[0] = b.w[0];
  *dataBsrr[1] = b.w[1];
  *wrBsrr = 1u << (BUS_WR.pin + 16);  // WR low
  (void)*wrOdr;                       // Read back so the low pulse has its full width.
  __asm__ volatile("nop\n nop\n nop\n nop");
  *wrBsrr = 1u << BUS_WR.pin;         // Rising WR latches the byte.
  (void)*wrOdr;
}

void busCommand(uint8_t command) {
  *cdBsrr = 1u << (BUS_CD.pin + 16);
  busWrite(busEncode(command));
  *cdBsrr = 1u << BUS_CD.pin;
}

void busData16(uint16_t v) {
  busWrite(busEncode(v >> 8));
  busWrite(busEncode(v & 0xFF));
}

// Same command sequence as the library's setAddrWindow().
void busWindow(int x0, int y0, int x1, int y1) {
  busCommand(0x2A); busData16(x0); busData16(x1);
  busCommand(0x2B); busData16(y0); busData16(y1);
  busCommand(0x2C);
}

void fillArea(int x, int y, int w, int h, uint16_t color) {
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x + w > display.width()) w = display.width() - x;
  if (y + h > display.height()) h = display.height() - y;
  if (w <= 0 || h <= 0) return;
  if (!fastBus) {
    display.fillRect(x, y, w, h, color);
    return;
  }
  busWindow(x, y, x + w - 1, y + h - 1);
  BusByte hi = busEncode(color >> 8), lo = busEncode(color & 0xFF);
  for (uint32_t n = (uint32_t)w * h; n; --n) { busWrite(hi); busWrite(lo); }
}

// Classic 6x8 Adafruit font cells, scaled by size, streamed one cell at a time.
void drawText(int x, int y, int size, uint16_t fg, uint16_t bg, const uint8_t* text, int length) {
  size = constrain(size, 1, 6);
  if (!fastBus) {
    String s;
    for (int i = 0; i < length; ++i) s += (char)text[i];
    display.setTextSize(size);
    display.setCursor(x, y);
    display.setTextColor(fg, bg);
    display.print(s);
    display.setTextSize(2);  // The preview screens expect size 2.
    return;
  }
  int cw = 6 * size, ch = 8 * size;
  if (y < 0 || y + ch > display.height()) return;
  BusByte ink[2] = {busEncode(fg >> 8), busEncode(fg & 0xFF)};
  BusByte paper[2] = {busEncode(bg >> 8), busEncode(bg & 0xFF)};
  for (int i = 0; i < length && x >= 0 && x + cw <= display.width(); ++i, x += cw) {
    uint8_t c = text[i];
    if (c >= 176) c++;  // Match Adafruit_GFX's classic (non-cp437) mapping.
    const uint8_t* glyph = font + c * 5;
    busWindow(x, y, x + cw - 1, y + ch - 1);
    for (int py = 0; py < ch; ++py) {
      int row = py / size;
      for (int px = 0; px < cw; ++px) {
        int col = px / size;
        const BusByte* p = (col < 5 && (glyph[col] >> row & 1)) ? ink : paper;
        busWrite(p[0]);
        busWrite(p[1]);
      }
    }
  }
}

int16_t read16(const uint8_t* p) { return (int16_t)(p[0] | (p[1] << 8)); }

// Commands, little-endian: 'C' color | 'R' x y w h color | 'T' x y size fg bg len text.
void runDrawCommands(const uint8_t* p, size_t n) {
  size_t i = 0;
  while (i < n) {
    uint8_t op = p[i];
    if (op == 'C' && i + 3 <= n) {
      fillArea(0, 0, display.width(), display.height(), (uint16_t)read16(p + i + 1));
      i += 3;
    } else if (op == 'R' && i + 11 <= n) {
      fillArea(read16(p + i + 1), read16(p + i + 3),
               constrain(read16(p + i + 5), 0, 480), constrain(read16(p + i + 7), 0, 320),
               (uint16_t)read16(p + i + 9));
      i += 11;
    } else if (op == 'T' && i + 11 <= n && i + 11 + p[i + 10] <= n) {
      drawText(read16(p + i + 1), read16(p + i + 3), p[i + 5],
               (uint16_t)read16(p + i + 6), (uint16_t)read16(p + i + 8), p + i + 11, p[i + 10]);
      i += 11 + p[i + 10];
    } else {
      return;  // Malformed batch: stop rather than draw garbage.
    }
  }
}

void keepAlive() {
  lastFrameAt = millis();
  waiting = false;
}

// Draws one batch of queued commands (used when a frame needs several calls).
bool gameDraw(MsgPack::bin_t<uint8_t> cmds) {
  if (videoSession) return false;
  runDrawCommands(cmds.data(), cmds.size());
  keepAlive();
  return true;
}

// One call per frame: draw the last batch, then return fresh controls as
// "video,connected,buttons,x,y,ax,ay,az,reset". reset=1 means the waiting
// screen replaced the game and Python must redraw everything.
String gameFrame(MsgPack::bin_t<uint8_t> cmds) {
  int reset = screenReset ? 1 : 0;
  if (!videoSession) {
    screenReset = false;
    runDrawCommands(cmds.data(), cmds.size());
    keepAlive();
  }
  int v[8];
  sampleInputs(v);
  char line[96];
  snprintf(line, sizeof(line), "%d,%d,%d,%d,%d,%d,%d,%d,%d",
           v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], reset);
  return String(line);
}

void setup() {
  Modulino.begin(Wire1);
  buttons.begin();
  movementReady = movement.begin();
  display.begin();
  display.setRotation(1);  // Landscape: 480 x 320.
  display.fillScreen(TFT_BLACK);
  display.setTextSize(2);
  display.setTextWrap(false);
#if ARCADE_FAST_TFT
  fastBus = fastBusBegin();
#endif
  textLine(10, "UNO Q arcade starter");
  display.drawRect(12, 160, 456, 148, TFT_WHITE);
  showWaiting();
  if (Bridge.begin()) {
    Bridge.provide_safe("arcade_read_inputs", readInputs);
    Bridge.provide_safe("arcade_draw_frame", drawFrame);
    Bridge.provide_safe("arcade_video_begin", beginVideo);
    Bridge.provide_safe("arcade_video_tile", videoTile);
    Bridge.provide_safe("arcade_video_poll", pollVideo);
    Bridge.provide_safe("arcade_video_end", endVideo);
    Bridge.provide_safe("game_frame", gameFrame);
    Bridge.provide_safe("game_draw", gameDraw);
  } else {
    textLine(36, "Bridge failed: restart app");
  }
}

void loop() {
  if (!waiting && millis() - lastFrameAt > 1500) showWaiting();
  delay(1);  // Bridge serves one call per loop pass; a short pass keeps input lag low.
}
