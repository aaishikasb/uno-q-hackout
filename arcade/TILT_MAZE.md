# Tilt Maze 🎱

A tilt-controlled maze game for the Arduino UNO Q arcade console, built at Build Day with Qualcomm (Northeastern, 2026-10-24), Track 2.

Hold the console flat, press the stick, then **tilt the whole console** to roll an orange ball through three mazes to the green **E** exit. Grey rings are holes: roll over one and you lose a life and restart the maze. Each maze has a clock. Three lives for the whole run, three mazes, score is 100 per maze plus every second left on the clock.

## Controls

| Control | Action |
| --- | --- |
| **Tilt the console** (Modulino Movement) | Roll the ball |
| Joystick press | Start / play again. Starting also **zeroes** the tilt sensor at the current angle |
| **B** (on the start screen) | Re-zero the tilt sensor without starting |
| Joystick axes | Roll the ball **only if the Movement module is missing** |
| **A** | Start / play again **only if the Joystick module is missing** |
| Button LEDs | Show lives left during play (3 lit = 3 lives) |

The start screen has a **tilt test** box in the corner: the dot shows the current tilt and turns green when the console reads flat, so you can check calibration before every run.

## Rules

- Reach the green **E** cell → maze clear, **+100 + seconds left**.
- Ball center over a hole → **lose a life**, ball returns to the start of the maze.
- Clock runs out → game over.
- Three mazes: maze 1 is open with loops and no holes, maze 2 has 3 holes in dead ends, maze 3 is a full maze with 5 holes and the most time pressure.
- Best score is saved on the board in `data/best.json`, which survives `make flash`.

## What runs where

| Part | File | Role |
| --- | --- | --- |
| Linux / Python (MPU) | `python/maze.py` | Maze generation (seeded, verified solvable), ball physics, collisions, holes, lives, timers, scoring, state machine. No hardware access; unit-tested. |
| Linux / Python (MPU) | `python/main.py` | Bridge loop. Sends each maze once with `arcade_maze_load`, then one `arcade_maze_frame` call per frame that draws **and returns the fresh sensor snapshot**, so there is a single Bridge round trip per frame. |
| Zephyr / Arduino (MCU) | `sketch/sketch.ino` | Reads the Modulinos over Qwiic (`Wire1`), drives the button LEDs, draws the TFT. The maze is drawn once per level; each frame only redraws the cells under the old ball, the ball, and whichever HUD number or timer-bar slice changed. |

Frame sent each loop: `mode, ball_x, ball_y, level, lives, time_left_pct, score, best, connected, extra`. The sketch bounds every value before drawing.

## Launch

### App Lab (import)

1. `make package` (or re-zip `app.yaml`, `python/`, `sketch/` with `app.yaml` at the archive root) to produce `zip/uno-q-arcade.zip`.
2. In App Lab **My Apps**, import the ZIP and select the UNO Q.
3. In `sketch/sketch.ino`, set `ARCADE_TFT_HX8357D` to `1` (HX8357D, default) or `0` (RM68140) to match the console's display controller.
4. Run the app. The first run downloads dependencies and takes a few minutes.

### Terminal (adb + Arduino App CLI on the board)

```sh
make flash     # package, push, compile, start
make logs      # follow Python output in a second terminal
make stop
```

### Local tests (no board needed)

```sh
python3 -m unittest discover -s tests -v
```

## Calibration

No numbers to edit for the basic setup: **the tilt zero is captured when you press the stick to start**, so whatever angle the console is held at that moment becomes "flat". Press **B** on the start screen to re-zero at any time and watch the tilt-test dot turn green.

The Movement module in the Build Day console is mounted upright: gravity sits on `ay`, left/right tilt moves `ax`, front/back tilt moves `az`. The shipped constants (`TILT_AXIS_X = 0`, `TILT_AXIS_Y = 2`, `INVERT_TILT_X = True`, `INVERT_TILT_Y = False`) were set by reading the raw values on the console. If the ball rolls the wrong way on a differently mounted module, change the constants at the top of `python/maze.py`:

| Constant | Meaning |
| --- | --- |
| `TILT_AXIS_X`, `TILT_AXIS_Y` | Which accelerometer axis (0=ax, 1=ay, 2=az) moves the ball left/right and up/down |
| `INVERT_TILT_X`, `INVERT_TILT_Y` | Flip a direction |
| `TILT_DEAD_ZONE_MG`, `TILT_MAX_MG` | Tilt ignored below the dead zone; full acceleration at the max |
| `ACCEL_PX`, `MAX_SPEED`, `DAMPING` | Feel: how hard the ball accelerates, its top speed, how fast it settles |
| `INVERT_STICK_X`, `INVERT_STICK_Y` | Joystick fallback directions (match `python/preview.py`) |

## Robustness

- **Movement module missing**: the joystick rolls the ball instead, and the start screen says so.
- **Joystick missing**: **A** starts the game, the prompt changes accordingly.
- **Both missing**: the screen shows **PAUSED** with the cause, the clock freezes, and play resumes where it left off when a module is back.
- Button presses are edge-detected, the result screen ignores presses for its first second, and physics is sub-stepped so the ball cannot tunnel through a wall during a Bridge hiccup.
- If Python stops sending frames for 1.5 s the MCU falls back to the starter's waiting screen and turns the LEDs off.

## Verified on the console

Tested on a prepared Build Day console (Debian 13 image, App CLI 0.13.0, Zephyr core 1.0.0, HX8357D panel): start screen, live tilt-test marker, button LEDs, stick start, Bridge frame loop all run from `make flash`.

## Troubleshooting

| Symptom | Cause we hit | Fix |
| --- | --- | --- |
| Python logs `method arcade_read_inputs not available`, no serial output, TFT white | Sketch built with Zephyr core 0.55.2 on a board whose runtime is 1.0.0: the upload succeeds but the sketch never runs | `sketch.yaml` pins `arduino:zephyr (1.0.0)` (the version the board's bundled examples use) |
| Bridge works and button LEDs light, but the TFT stays pure white with either controller setting | TFT shield not fully seated on the headers (control lines read about 1.9 V instead of 3.3 V, controller ID reads as zeros) | Power off, press the shield firmly onto the UNO headers, power on. After reseating, register `0xBF` reads `00 01 62 83 57 FF`, which identifies the HX8357D |
| First `make flash` takes 15+ minutes | Core, toolchain and three libraries download and compile on the board | Needs Internet once (a phone hotspot via `nmcli dev wifi connect` works); later flashes take about a minute |

## Hardware

Preassembled UNO Q arcade console: Arduino UNO Q, Modulino Buttons (`0x3E`), Modulino Joystick (`0x2C`), Modulino Movement (`0x6A`) over Qwiic, DIYables 3.5" 480×320 TFT shield (HX8357D). See [README.md](README.md) for wiring, pins, and the RetroArch option.

## Credits

- Starter code, hardware reference, and Bridge pattern: [aaishikasb/uno-q-hackout](https://github.com/aaishikasb/uno-q-hackout) (`arcade/` track), kept in `README.md`, `python/preview.py`, and the preview/video routines in the sketch.
- Enclosure and controls based on the [Arduino UNO Q Arcade Bundle](https://projecthub.arduino.cc/Arduino_Genuino/uno-q-arcade-bundle-b272c5).
- Libraries pinned in `sketch/sketch.yaml`: Arduino_RouterBridge, Arduino_Modulino, DIYables TFT Touch Shield, Adafruit GFX.
- Mazes are generated in code (depth-first carving); no external art or sound assets.
