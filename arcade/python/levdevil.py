"""Level Devil-style troll platformer for the UNO Q console.

Game rules run here in Python; the sketch only draws (game_* Bridge calls).
"""
import math
import struct

from preview import calibrated

W, H = 480, 320


def rgb(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


BG = rgb(245, 175, 60)
INK = rgb(25, 15, 10)
SOLID = rgb(70, 40, 20)
SPIKE = rgb(200, 20, 20)
DOOR = rgb(255, 255, 255)
SLIDER = rgb(40, 90, 220)

PW, PH = 14, 18      # player size
GRAVITY = 1400.0     # px/s^2
RUN = 170.0          # px/s
JUMP = 480.0         # px/s upward
MAX_FALL = 700.0     # px/s
JUMP_BUFFER = 0.12   # s; a jump pressed just before landing still counts
STICK_RUN = 40       # calibrated stick units before the player runs
TILT_X = (0, 1)      # Fallback (index into (ax, ay, az), sign) if the tilt check is skipped
TILT_LEARN = 250     # mg of tilt that answers the "tilt right" check
TILT_SPEED = 0.6     # slider px/s per mg of tilt
TILT_MAX = 220.0     # slider px/s
TILT_DEAD = 40       # mg around the level-start angle that counts as level
AUTO_SPEED = 70.0    # slider px/s when Movement is unavailable

# Rects are (x, y, w, h). A trap fires once per life when the player's centre x
# enters "when"; "remove" takes an index into solids. A slider is
# (x, y, w, h, x_min, x_max) and follows the console's tilt.
LEVELS = [
    {"name": "Easy start", "start": (20, 262), "door": (440, 240, 24, 40),
     "solids": [(0, 280, 230, 40), (230, 280, 70, 40), (300, 280, 180, 40)],
     "spikes": [],
     "traps": [{"when": (190, 480), "do": [("remove", 1)]}]},
    {"name": "Spiky", "start": (20, 262), "door": (440, 240, 24, 40),
     "solids": [(0, 280, 480, 40)],
     "spikes": [(180, 268, 30, 12)],
     "traps": [{"when": (290, 480), "do": [("spike", (330, 268, 40, 12))]},
               {"when": (400, 480), "do": [("door", (20, 240, 24, 40))]}]},
    {"name": "Mind the gap", "start": (20, 262), "door": (445, 240, 24, 40),
     "solids": [(0, 280, 140, 40), (220, 280, 120, 40), (370, 280, 110, 40)],
     "spikes": [],
     "traps": [{"when": (240, 480), "do": [("spike", (300, 268, 20, 12))]}]},
    {"name": "Tilt it", "start": (20, 262), "door": (445, 240, 24, 40),
     "solids": [(0, 280, 110, 40), (400, 280, 80, 40)],
     "spikes": [],
     "slider": (110, 280, 70, 12, 110, 330),
     "traps": [{"when": (410, 480), "do": [("door", (20, 240, 24, 40))]}]},
    {"name": "The devil", "start": (20, 262), "door": (450, 240, 24, 40),
     "solids": [(0, 280, 100, 40), (310, 280, 70, 40), (380, 280, 40, 40), (420, 280, 60, 40)],
     "spikes": [],
     "slider": (100, 280, 60, 12, 100, 250),
     "traps": [{"when": (330, 480), "do": [("remove", 2)]}]},
]

MAX_BATCH = 200  # Drawing bytes per Bridge call; the MCU accepts 256-byte messages.
INPUT_KEYS = ("video", "connected", "buttons", "x", "y", "ax", "ay", "az", "reset")

READY, PLAYING, CALIBRATE, RESULT = "ready", "playing", "calibrate", "result"


def overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class Game:
    def __init__(self, bridge):
        self.bridge = bridge
        self.cmds = []  # Drawing queued during a tick, sent with the next frame call.
        self.prev_buttons = 0
        self.connected = None
        self.tilt_axis = None  # Learned on the first tilt level: (index into (ax, ay), sign).
        self.new_game()

    def new_game(self):
        self.level = 0
        self.deaths = 0
        self.elapsed = 0.0
        self.state = READY
        self.load_level()

    def load_level(self):
        level = LEVELS[self.level]
        self.solids = list(level["solids"])
        self.spikes = list(level["spikes"])
        self.door = level["door"]
        self.fired = [False] * len(level["traps"])
        self.slider = list(level["slider"][:4]) if "slider" in level else None
        self.slider_rect = None
        self.slider_dir = 1
        self.tilt_zero = None  # Set from the first reading of each life.
        self.x, self.y = map(float, level["start"])
        self.vx = self.vy = 0.0
        self.on_ground = self.riding = False
        self.jump_buffer = 0.0
        self.drawn = None  # Player position on screen; None forces a full redraw.
        self.slider_drawn = None

    def exchange(self):
        """Send the queued drawing and return fresh inputs: one Bridge call per frame."""
        chunks, chunk = [], b""
        for cmd in self.cmds:
            if len(chunk) + len(cmd) > MAX_BATCH:
                chunks.append(chunk)
                chunk = b""
            chunk += cmd
        chunks.append(chunk)
        self.cmds = []
        # Fail fast so main.py can recover; a full-screen clear gets longer.
        timeout = lambda c: 5 if c[:1] == b"C" else 1
        for c in chunks[:-1]:
            self.bridge.call("game_draw", c, timeout=timeout(c))
        reply = self.bridge.call("game_frame", chunks[-1], timeout=timeout(chunks[-1]))
        return dict(zip(INPUT_KEYS, map(int, reply.split(","))))

    def clear(self, color):
        self.cmds = [struct.pack("<cH", b"C", color)]  # Anything queued before is covered.

    def rect(self, x, y, w, h, color):
        self.cmds.append(struct.pack("<chhhhH", b"R", x, y, w, h, color))

    def text(self, x, y, size, fg, bg, line):
        data = line.encode("ascii", "replace")[:60]
        self.cmds.append(struct.pack("<chhBHHB", b"T", x, y, size, fg, bg, len(data)) + data)

    def tick(self, inputs, dt):
        if inputs.get("reset"):
            self.drawn = None  # The sketch showed its waiting screen.
        stick_x, _, buttons, ax, ay, az, connected = calibrated(inputs)
        pressed = buttons & ~self.prev_buttons  # New presses only.
        self.prev_buttons = buttons
        if connected != self.connected:
            self.connected = connected
            self.drawn = None
        playable = bool(connected & 2)  # Running needs the joystick.
        jump = pressed & 9              # A or the stick press.

        if self.state == RESULT and pressed & 12:
            self.new_game()
        elif self.state == PLAYING and pressed & 4:
            self.load_level()
        elif self.state == READY and jump and playable:
            self.state = PLAYING
            self.drawn = None
        elif self.state == CALIBRATE:
            self.learn_tilt(ax, ay, pressed, connected)
        elif self.state == PLAYING and self.slider and connected & 4 and self.tilt_axis is None:
            # First tilt level: ask for a tilt to the right and learn which way is right.
            self.state = CALIBRATE
            self.tilt_base = (ax, ay)
            self.drawn = None
        elif self.state == PLAYING and playable:
            run = 0 if abs(stick_x) < STICK_RUN else (1 if stick_x > 0 else -1)
            tilt = None
            if connected & 4:
                index, sign = self.tilt_axis or TILT_X
                raw = (ax, ay, az)[index] * sign
                if self.tilt_zero is None:
                    self.tilt_zero = raw  # However the player holds it at the start counts as level.
                tilt = raw - self.tilt_zero
                if abs(tilt) < TILT_DEAD:
                    tilt = 0
            if jump:
                self.jump_buffer = JUMP_BUFFER
            self.step(run, tilt, dt)

        if self.drawn is None:
            self.redraw()
        elif self.state == PLAYING:
            self.draw_slider()
            self.draw_player()

    def learn_tilt(self, ax, ay, pressed, connected):
        if not connected & 4 or pressed & 1:  # Movement gone, or A skips the check.
            self.tilt_axis = self.tilt_axis or TILT_X
        else:
            deltas = (ax - self.tilt_base[0], ay - self.tilt_base[1])
            index = 0 if abs(deltas[0]) >= abs(deltas[1]) else 1
            if abs(deltas[index]) < TILT_LEARN:
                return
            self.tilt_axis = (index, 1 if deltas[index] > 0 else -1)
            # The reading from before the tilt is level, not the tilted one.
            self.tilt_zero = self.tilt_base[index] * self.tilt_axis[1]
        self.state = PLAYING
        self.drawn = None

    def box(self):
        return (self.x, self.y, PW, PH)

    def live_solids(self):
        solids = [s for s in self.solids if s]
        if self.slider:
            self.slider_rect = (round(self.slider[0]), *self.slider[1:])
            solids.append(self.slider_rect)
        return solids

    def move_slider(self, tilt, dt):
        if not self.slider:
            return
        lo, hi = LEVELS[self.level]["slider"][4:]
        if tilt is None:  # No Movement module: the platform patrols on its own.
            speed = AUTO_SPEED * self.slider_dir
        else:
            speed = max(-TILT_MAX, min(TILT_MAX, tilt * TILT_SPEED))
        x = max(lo, min(hi, self.slider[0] + speed * dt))
        if x == hi:
            self.slider_dir = -1
        elif x == lo:
            self.slider_dir = 1
        if self.riding:
            self.x += x - self.slider[0]
        self.slider[0] = x

    def step(self, run, tilt, dt):
        self.elapsed += dt
        self.move_slider(tilt, dt)
        self.jump_buffer = max(0.0, self.jump_buffer - dt)
        if self.jump_buffer and self.on_ground:
            self.vy = -JUMP
            self.jump_buffer = 0.0
        self.vx = run * RUN
        self.vy = min(MAX_FALL, self.vy + GRAVITY * dt)
        solids = self.live_solids()
        self.on_ground = self.riding = False
        # Small sub-steps so a fast fall cannot pass through a thin platform.
        steps = max(1, math.ceil(max(abs(self.vx), abs(self.vy)) * dt / 4))
        for _ in range(steps):
            self.x = max(0.0, min(W - PW, self.x + self.vx * dt / steps))
            for s in solids:
                if overlaps(self.box(), s):
                    self.x = s[0] - PW if self.vx > 0 else s[0] + s[2]
            self.y += self.vy * dt / steps
            for s in solids:
                if overlaps(self.box(), s):
                    if self.vy > 0:
                        self.y = s[1] - PH
                        self.on_ground = True
                        self.riding = s is self.slider_rect
                    else:
                        self.y = s[1] + s[3]
                    self.vy = 0.0

        self.fire_traps()
        box = self.box()
        if self.y > H or any(overlaps(box, s) for s in self.spikes):
            self.deaths += 1
            self.load_level()
        elif overlaps(box, self.door):
            if self.level + 1 < len(LEVELS):
                self.level += 1
                self.load_level()
            else:
                self.state = RESULT
                self.drawn = None

    def fire_traps(self):
        cx = self.x + PW / 2
        for i, trap in enumerate(LEVELS[self.level]["traps"]):
            lo, hi = trap["when"]
            if self.fired[i] or not lo <= cx <= hi:
                continue
            self.fired[i] = True
            for kind, arg in trap["do"]:
                if kind == "remove":
                    self.rect(*self.solids[arg], BG)
                    self.solids[arg] = None
                elif kind == "solid":
                    self.solids.append(arg)
                    self.rect(*arg, SOLID)
                elif kind == "spike":
                    self.spikes.append(arg)
                    self.rect(*arg, SPIKE)
                elif kind == "door":
                    self.rect(*self.door, BG)
                    self.door = arg
                    self.draw_door()

    def draw_door(self):
        x, y, w, h = self.door
        self.rect(x, y, w, h, INK)
        self.rect(x + 3, y + 3, w - 6, h - 3, DOOR)

    def redraw(self):
        self.clear(BG)
        for s in self.solids:
            if s:
                self.rect(*s, SOLID)
        for s in self.spikes:
            self.rect(*s, SPIKE)
        self.draw_door()
        self.slider_drawn = None
        self.draw_slider()
        level = LEVELS[self.level]
        self.text(8, 4, 2, INK, BG,
             f"{self.level + 1}/{len(LEVELS)} {level['name']}   Deaths {self.deaths}")
        if not self.connected & 1:
            self.text(8, 22, 1, INK, BG, "Buttons off: press the stick to jump")
        elif self.slider and not self.connected & 4:
            self.text(8, 22, 1, INK, BG, "Tilt off: the blue platform moves itself")
        self.drawn = (round(self.x), round(self.y))
        self.rect(*self.drawn, PW, PH, INK)
        if self.state != PLAYING or not self.connected & 2:
            self.draw_overlay()

    def draw_overlay(self):
        if not self.connected & 2:
            lines = ["Joystick disconnected", "Check the Qwiic cable.", "Game resumes when it's back"]
        elif self.state == CALIBRATE:
            lines = ["Tilt check", "Tilt the console to", "the RIGHT, then level", "it again.  A skips"]
        elif self.state == READY:
            lines = ["LEVEL DEVIL", "Reach the door.", "Trust nothing.",
                     "Stick run   A jump", "Tilt moves blue floors", "Press A to start"]
        else:
            lines = ["You escaped!", f"Deaths {self.deaths}  Time {self.elapsed:.0f}s",
                     "Press C to play again"]
        height = 40 + 24 * len(lines)
        self.rect(60, 60, 360, height, INK)
        self.rect(63, 63, 354, height - 6, BG)
        for i, line in enumerate(lines):
            self.text(80, 80 + 24 * i, 2, INK, BG, line)

    def draw_player(self):
        pos = (round(self.x), round(self.y))
        if pos == self.drawn:
            return
        old = (*self.drawn, PW, PH)
        self.rect(*old, BG)
        if overlaps(old, self.door):
            self.draw_door()
        self.rect(*pos, PW, PH, INK)
        self.drawn = pos

    def draw_slider(self):
        if not self.slider:
            return
        x = round(self.slider[0])
        old = self.slider_drawn
        if x == old:
            return
        _, y, w, h = self.slider
        if old is None or abs(x - old) >= w:
            if old is not None:
                self.rect(old, y, w, h, BG)
            self.rect(x, y, w, h, SLIDER)
        elif x > old:  # Erase the trailing strip, paint the leading one.
            self.rect(old, y, x - old, h, BG)
            self.rect(old + w, y, x - old, h, SLIDER)
        else:
            self.rect(x + w, y, old - x, h, BG)
            self.rect(x, y, old - x, h, SLIDER)
        self.slider_drawn = x
