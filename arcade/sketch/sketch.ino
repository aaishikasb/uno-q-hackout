#include <Arduino.h>
#include <Arduino_RouterBridge.h>
#include <Arduino_Modulino.h>
#include <DIYables_TFT_Touch_Shield.h>
#include <math.h>
#include "video_protocol.h"

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

// ---- Tilt Maze drawing state ----
const uint16_t TFT_GREEN = 0x07E0;
const uint16_t TFT_RED = 0xF800;
const uint16_t TFT_YELLOW = 0xFFE0;
const uint16_t TFT_ORANGE = 0xFD20;
const uint16_t TFT_WALL = 0x2A9C;       // muted blue
const uint16_t TFT_WALL_EDGE = 0x1B14;  // darker blue outline
const uint16_t TFT_HOLE = 0x4208;       // dark grey rim
const int MAZE_COLS = 20, MAZE_ROWS = 11, MAZE_CELL = 24, MAZE_Y = 40;
const int BALL_R = 8;
const int BAR_X = 300, BAR_Y = 12, BAR_W = 168, BAR_H = 16;
const int TILT_BOX_X = 380, TILT_BOX_Y = 212, TILT_BOX_S = 88;
char mazeGrid[MAZE_COLS * MAZE_ROWS];
bool mazeLoaded = false;
bool mazeDirty = false;
bool gameMode = false;
int gLastMode = -1, gBallX = -1, gBallY = -1, gLastLevel = -1, gLastLives = -1;
int gLastScore = -1, gLastBarW = -1, gLastConnected = -1, gMarkerX = -1, gMarkerY = -1;

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

String readInputs() {
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
    // In the game the LEDs show the lit lane instead of mirroring presses.
    if (!gameMode) buttons.setLeds(buttonData[0], buttonData[1], buttonData[2]);
  }
  if (joystickOk && stickData[2]) pressed |= 8;
  char json[180];
  snprintf(json, sizeof(json),
           "{\"video\":%d,\"connected\":%d,\"buttons\":%d,\"x\":%d,\"y\":%d,"
           "\"ax\":%d,\"ay\":%d,\"az\":%d}",
           videoSession, connected, pressed,
           joystickOk ? 128 - (int)stickData[0] : 0,
           joystickOk ? 128 - (int)stickData[1] : 0,
           movementOk ? (int)(constrain(ax, -16.0f, 16.0f) * 1000) : 0,
           movementOk ? (int)(constrain(ay, -16.0f, 16.0f) * 1000) : 0,
           movementOk ? (int)(constrain(az, -16.0f, 16.0f) * 1000) : 0);
  return String(json);
}

void textLine(int y, const char* text) {
  display.setCursor(12, y);
  display.setTextColor(TFT_WHITE, TFT_BLACK);
  display.print(text);
}

void showWaiting() {
  if (videoSession || gameMode) {
    videoSession = 0;
    gameMode = false;
    gLastMode = -1;
    buttons.setLeds(false, false, false);
    display.fillScreen(TFT_BLACK);
    textLine(10, "UNO Q arcade starter");
    display.drawRect(12, 160, 456, 148, TFT_WHITE);
  }
  display.fillRect(12, 36, 456, 112, TFT_BLACK);
  textLine(36, "Waiting for App Lab...");
  if (lastX >= 0) display.fillCircle(lastX, lastY, 6, TFT_BLACK);
  lastX = -1;
  waiting = true;
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

// ---- Tilt Maze drawing ----

void textAt(int x, int y, int size, uint16_t color, const char* text) {
  display.setTextSize(size);
  display.setTextColor(color, TFT_BLACK);
  display.setCursor(x, y);
  display.print(text);
  display.setTextSize(2);
}

// Center `text` of `size` on the 480-wide screen at row y.
void textCentered(int y, int size, uint16_t color, const char* text) {
  int width = strlen(text) * 6 * size;
  textAt((480 - width) / 2, y, size, color, text);
}

void drawCell(int col, int row) {
  if (col < 0 || col >= MAZE_COLS || row < 0 || row >= MAZE_ROWS) return;
  int x = col * MAZE_CELL, y = MAZE_Y + row * MAZE_CELL;
  int cx = x + MAZE_CELL / 2, cy = y + MAZE_CELL / 2;
  char cell = mazeLoaded ? mazeGrid[row * MAZE_COLS + col] : '#';
  if (cell == '#') {
    display.fillRect(x, y, MAZE_CELL, MAZE_CELL, TFT_WALL);
    display.drawRect(x, y, MAZE_CELL, MAZE_CELL, TFT_WALL_EDGE);
    return;
  }
  display.fillRect(x, y, MAZE_CELL, MAZE_CELL, TFT_BLACK);
  if (cell == 'O') {
    display.fillCircle(cx, cy, 9, TFT_HOLE);
    display.fillCircle(cx, cy, 6, TFT_BLACK);
  } else if (cell == 'E') {
    display.fillRect(x + 3, y + 3, MAZE_CELL - 6, MAZE_CELL - 6, TFT_GREEN);
    display.setTextSize(1);
    display.setTextColor(TFT_BLACK, TFT_GREEN);
    display.setCursor(cx - 2, cy - 3);
    display.print("E");
    display.setTextSize(2);
  }
}

void drawMaze() {
  for (int row = 0; row < MAZE_ROWS; ++row)
    for (int col = 0; col < MAZE_COLS; ++col) drawCell(col, row);
  mazeDirty = false;
  gBallX = gBallY = -1;
}

// Redraw the cells under the previous ball position, then draw the ball.
void drawBall(int x, int y) {
  if (x == gBallX && y == gBallY) return;
  if (gBallX >= 0) {
    int c0 = (gBallX - BALL_R) / MAZE_CELL, c1 = (gBallX + BALL_R) / MAZE_CELL;
    int r0 = (gBallY - BALL_R - MAZE_Y) / MAZE_CELL, r1 = (gBallY + BALL_R - MAZE_Y) / MAZE_CELL;
    for (int row = r0; row <= r1; ++row)
      for (int col = c0; col <= c1; ++col) drawCell(col, row);
  }
  display.fillCircle(x, y, BALL_R, TFT_ORANGE);
  display.fillCircle(x - 3, y - 3, 2, TFT_WHITE);
  gBallX = x;
  gBallY = y;
}

void drawTimeBar(int pct) {
  int width = BAR_W * pct / 100;
  if (width == gLastBarW) return;
  uint16_t color = pct > 25 ? TFT_YELLOW : TFT_RED;
  if (gLastBarW < 0 || (pct <= 25 && gLastBarW > BAR_W / 4)) {
    display.fillRect(BAR_X, BAR_Y, width, BAR_H, color);
    display.fillRect(BAR_X + width, BAR_Y, BAR_W - width, BAR_H, TFT_BLACK);
  } else if (width < gLastBarW) {
    display.fillRect(BAR_X + width, BAR_Y, gLastBarW - width, BAR_H, TFT_BLACK);
  } else {
    display.fillRect(BAR_X + gLastBarW, BAR_Y, width - gLastBarW, BAR_H, color);
  }
  gLastBarW = width;
}

void drawHud(int level, int lives, int score) {
  char line[32];
  if (level != gLastLevel) {
    snprintf(line, sizeof(line), "Maze %d/3", level);
    textAt(6, 12, 2, TFT_WHITE, line);
    gLastLevel = level;
  }
  if (lives != gLastLives) {
    snprintf(line, sizeof(line), "Lives %d", lives);
    textAt(126, 12, 2, lives <= 1 ? TFT_RED : TFT_WHITE, line);
    buttons.setLeds(lives >= 1, lives >= 2, lives >= 3);  // LEDs count lives
    gLastLives = lives;
  }
  if (score != gLastScore) {
    snprintf(line, sizeof(line), "%5d", score);
    textAt(222, 12, 2, TFT_YELLOW, line);
    gLastScore = score;
  }
}

void drawStartHint(int y, int connected) {
  display.fillRect(0, y, 380, 16, TFT_BLACK);
  const char* hint = connected & 2 ? "press the STICK to start" : "press A to start";
  int width = strlen(hint) * 12;
  textAt((380 - width) / 2, y, 2, TFT_CYAN, hint);
}

void drawTiltMarker(int mx, int my) {
  int x = TILT_BOX_X + TILT_BOX_S / 2 + mx * 38 / 50;
  int y = TILT_BOX_Y + TILT_BOX_S / 2 + my * 38 / 50;
  if (x == gMarkerX && y == gMarkerY) return;
  if (gMarkerX >= 0) display.fillCircle(gMarkerX, gMarkerY, 5, TFT_BLACK);
  display.drawRect(TILT_BOX_X, TILT_BOX_Y, TILT_BOX_S, TILT_BOX_S, TFT_WHITE);
  display.drawFastHLine(TILT_BOX_X + 4, TILT_BOX_Y + TILT_BOX_S / 2, TILT_BOX_S - 8, TFT_HOLE);
  display.drawFastVLine(TILT_BOX_X + TILT_BOX_S / 2, TILT_BOX_Y + 4, TILT_BOX_S - 8, TFT_HOLE);
  display.fillCircle(x, y, 5, (mx == 0 && my == 0) ? TFT_GREEN : TFT_ORANGE);
  gMarkerX = x;
  gMarkerY = y;
}

// Python sends the 20x11 grid once per level: '#' wall, '.' floor, 'S', 'E', 'O' hole.
bool loadMaze(MsgPack::bin_t<uint8_t> grid) {
  if (grid.size() != (size_t)(MAZE_COLS * MAZE_ROWS)) return false;
  for (int i = 0; i < MAZE_COLS * MAZE_ROWS; ++i) {
    char c = (char)grid.data()[i];
    mazeGrid[i] = (c == '#' || c == 'O' || c == 'E' || c == 'S') ? c : '.';
  }
  mazeLoaded = true;
  mazeDirty = true;
  return true;
}

// mode: 0 ready, 1 playing, 2 level clear, 3 result, 4 paused.
// Returns the fresh input snapshot so Python needs one round trip per frame.
String drawMazeFrame(int mode, int x, int y, int level, int lives, int pct,
                     int score, int best, int connected, int extra) {
  if (videoSession) return String("");  // RetroArch owns the display.
  mode = constrain(mode, 0, 4);
  x = constrain(x, BALL_R, 479 - BALL_R);
  y = constrain(y, MAZE_Y + BALL_R, MAZE_Y + MAZE_ROWS * MAZE_CELL - BALL_R);
  level = constrain(level, 1, 3);
  lives = constrain(lives, 0, 3);
  pct = constrain(pct, 0, 100);
  score = constrain(score, 0, 99999);
  best = constrain(best, 0, 99999);
  connected &= 7;
  extra = constrain(extra, 0, 99999);

  if (!gameMode) {
    gameMode = true;
    gLastMode = -1;
  }
  bool modeChanged = mode != gLastMode;
  char line[48];
  if (modeChanged && mode != 2) {  // the clear banner sits on top of the maze
    display.fillScreen(TFT_BLACK);
    gLastLevel = gLastLives = gLastScore = -1;
    gLastBarW = -1;
    gLastConnected = -1;
    gMarkerX = gMarkerY = -1;
    gBallX = gBallY = -1;
  }
  gLastMode = mode;

  switch (mode) {
    case 0:  // Ready
      if (modeChanged) {
        textCentered(44, 4, TFT_WHITE, "TILT MAZE");
        textCentered(96, 2, TFT_WHITE, "Tilt the console to roll the ball");
        textCentered(120, 2, TFT_GREEN, "Reach the green E exit");
        textCentered(144, 2, TFT_RED, "Stay out of the holes");
        textCentered(168, 2, TFT_WHITE, "3 lives, 3 mazes, beat the clock");
        textAt(24, 216, 2, TFT_WHITE, "Hold the console flat,");
        snprintf(line, sizeof(line), "B: re-zero   Best %d", best);
        textAt(24, 276, 2, TFT_YELLOW, line);
        textAt(TILT_BOX_X + 20, TILT_BOX_Y - 12, 1, TFT_WHITE, "tilt test");
        buttons.setLeds(true, true, true);
      }
      if (connected != gLastConnected) drawStartHint(240, connected);
      drawTiltMarker(extra / 101 - 50, extra % 101 - 50);
      break;
    case 1:  // Playing
      if (modeChanged || mazeDirty) {
        if (!modeChanged) display.fillRect(0, MAZE_Y, 480, MAZE_ROWS * MAZE_CELL, TFT_BLACK);
        display.drawRect(BAR_X - 1, BAR_Y - 1, BAR_W + 2, BAR_H + 2, TFT_WHITE);
        gLastBarW = -1;
        drawMaze();
      }
      drawHud(level, lives, score);
      drawTimeBar(pct);
      drawBall(x, y);
      break;
    case 2:  // Level clear banner over the finished maze
      if (modeChanged) {
        display.fillRect(84, 112, 312, 96, TFT_BLACK);
        display.drawRect(84, 112, 312, 96, TFT_GREEN);
        snprintf(line, sizeof(line), "MAZE %d CLEAR", level);
        textCentered(126, 3, TFT_GREEN, line);
        snprintf(line, sizeof(line), "+%d points", extra);
        textCentered(164, 2, TFT_YELLOW, line);
        gBallX = gBallY = -1;
      }
      drawHud(level, lives, score);
      break;
    case 3:  // Result
      if (modeChanged) {
        if (extra) textCentered(64, 4, TFT_GREEN, "YOU WIN!");
        else textCentered(64, 4, TFT_RED, "GAME OVER");
        snprintf(line, sizeof(line), "Score %d   Best %d", score, best);
        textCentered(130, 2, TFT_WHITE, line);
        if (score > 0 && score >= best) textCentered(166, 3, TFT_YELLOW, "NEW BEST!");
        buttons.setLeds(false, false, false);
      }
      if (connected != gLastConnected) {
        display.fillRect(0, 240, 480, 16, TFT_BLACK);
        textCentered(240, 2, TFT_CYAN,
                     connected & 2 ? "Press the STICK to play again" : "Press A to play again");
      }
      break;
    case 4:  // Paused: nothing can steer the ball
      if (modeChanged) {
        textCentered(100, 3, TFT_RED, "PAUSED");
        textCentered(150, 2, TFT_WHITE, "No tilt sensor or joystick");
        textCentered(176, 2, TFT_WHITE, "Check the Qwiic cables");
        textCentered(202, 2, TFT_WHITE, "The game resumes automatically");
      }
      break;
  }
  gLastConnected = connected;
  lastFrameAt = millis();
  waiting = false;
  return readInputs();
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

void setup() {
  Modulino.begin(Wire1);
  buttons.begin();
  movementReady = movement.begin();
  display.begin();
  display.setRotation(1);  // Landscape: 480 x 320.
  display.fillScreen(TFT_BLACK);
  display.setTextSize(2);
  display.setTextWrap(false);
  textLine(10, "UNO Q arcade starter");
  display.drawRect(12, 160, 456, 148, TFT_WHITE);
  showWaiting();
  if (Bridge.begin()) {
    Bridge.provide_safe("arcade_read_inputs", readInputs);
    Bridge.provide_safe("arcade_draw_frame", drawFrame);
    Bridge.provide_safe("arcade_maze_load", loadMaze);
    Bridge.provide_safe("arcade_maze_frame", drawMazeFrame);
    Bridge.provide_safe("arcade_video_begin", beginVideo);
    Bridge.provide_safe("arcade_video_tile", videoTile);
    Bridge.provide_safe("arcade_video_poll", pollVideo);
    Bridge.provide_safe("arcade_video_end", endVideo);
  } else {
    textLine(36, "Bridge failed: restart app");
  }
}

void loop() {
  if (!waiting && millis() - lastFrameAt > 1500) showWaiting();
  delay(5);
}
