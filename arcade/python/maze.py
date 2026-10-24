"""Tilt Maze: roll a ball through three mazes by tilting the console.

Pure game rules with no hardware access. `Game.update()` takes the raw input
snapshot from `arcade_read_inputs` (or the value returned by
`arcade_maze_frame`); `Game.frame()` returns the integers the sketch draws.

Grid: 20 columns x 11 rows of 24 px cells, drawn at y = 40 on the 480x320
TFT. Legend: `#` wall, `.` floor, `S` start, `E` exit, `O` hole.
"""

import math

# Button bits from the sketch.
A, B, C, STICK = 1, 2, 4, 8
# Connection bits.
CONN_BUTTONS, CONN_JOYSTICK, CONN_MOVEMENT = 1, 2, 4

# Modes sent to the sketch.
MODE_READY, MODE_PLAYING, MODE_CLEAR, MODE_RESULT, MODE_PAUSED = 0, 1, 2, 3, 4

COLS, ROWS, CELL = 20, 11, 24
GRID_X, GRID_Y = 0, 40
BALL_R = 7                 # collision half-size (drawn radius is 8)
HOLE_R = 9

# ---- Tuning: change these on the console until rolling feels right ----
TILT_AXIS_X = 0            # index into (ax, ay, az) that moves the ball left/right
TILT_AXIS_Y = 2            # index that moves the ball up/down the screen (az: module is mounted upright, gravity on ay)
INVERT_TILT_X = True
INVERT_TILT_Y = False
TILT_DEAD_ZONE_MG = 25     # ignore tiny tilt
TILT_MAX_MG = 350          # this much tilt gives full acceleration
ACCEL_PX = 1000.0          # px/s^2 at full tilt
MAX_SPEED = 200.0          # px/s
DAMPING = 2.5              # per second, velocity *= exp(-DAMPING * dt); higher = less floaty
JOYSTICK_DEAD_ZONE = 26
INVERT_STICK_X = False
INVERT_STICK_Y = True
MAX_DT = 0.1               # cap physics step when Bridge hiccups
START_LIVES = 3
CLEAR_PAUSE = 1.8          # seconds the "level clear" banner stays
RESULT_COOLDOWN = 1.0

def generate(seed, extra_openings=0, holes=0):
    """Perfect maze on a 9x5 cell lattice (odd columns 1..17, odd rows 1..9),
    carved with a seeded depth-first walk. `extra_openings` knocks out extra
    walls to add loops (easier). `holes` turns that many dead ends into traps,
    so a wrong turn costs a life while the S->E path stays open."""
    import random
    rng = random.Random(seed)
    grid = [["#"] * COLS for _ in range(ROWS)]
    cells = [(c, r) for c in range(1, 18, 2) for r in range(1, 10, 2)]
    for c, r in cells:
        grid[r][c] = "."
    visited = {(1, 1)}
    stack = [(1, 1)]
    while stack:
        c, r = stack[-1]
        options = [(c + dc, r + dr, c + dc // 2, r + dr // 2)
                   for dc, dr in ((2, 0), (-2, 0), (0, 2), (0, -2))
                   if (c + dc, r + dr) in visited.symmetric_difference(set(cells))
                   and (c + dc, r + dr) in set(cells)]
        if not options:
            stack.pop()
            continue
        nc, nr, wc, wr = rng.choice(options)
        grid[wr][wc] = "."
        visited.add((nc, nr))
        stack.append((nc, nr))
    walls = [(c, r) for c in range(2, 17) for r in range(1, 10)
             if grid[r][c] == "#" and (c + r) % 2 == 1
             and 1 <= c <= 17 and 1 <= r <= 9]
    rng.shuffle(walls)
    for c, r in walls[:extra_openings]:
        grid[r][c] = "."

    def exits(c, r):
        return sum(grid[r + dr][c + dc] != "#"
                   for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    dead_ends = [(c, r) for c, r in cells if exits(c, r) == 1
                 and (c, r) not in ((1, 1), (17, 9))]
    rng.shuffle(dead_ends)
    for c, r in dead_ends[:holes]:
        grid[r][c] = "O"
    grid[1][1] = "S"
    grid[9][17] = "E"
    return ["".join(row) for row in grid]


LEVELS = [
    {"time": 45, "grid": generate(seed=11, extra_openings=10, holes=0)},
    {"time": 60, "grid": generate(seed=23, extra_openings=3, holes=3)},
    {"time": 75, "grid": generate(seed=37, extra_openings=0, holes=5)},
]


class Level:
    def __init__(self, spec):
        self.grid = spec["grid"]
        self.time_limit = spec["time"]
        assert len(self.grid) == ROWS and all(len(r) == COLS for r in self.grid)
        self.start = self._find("S")
        self.exit = self._find("E")
        self.holes = [(c, r) for r in range(ROWS) for c in range(COLS)
                      if self.grid[r][c] == "O"]

    def _find(self, ch):
        for r, row in enumerate(self.grid):
            if ch in row:
                return row.index(ch), r
        raise ValueError(f"level has no {ch}")

    def wall(self, col, row):
        if not (0 <= col < COLS and 0 <= row < ROWS):
            return True
        return self.grid[row][col] == "#"

    def wire(self):
        """Grid as one string for arcade_maze_load."""
        return "".join(self.grid)

    def solvable(self):
        """Breadth-first search from S to E, treating holes as blocked."""
        seen = {self.start}
        queue = [self.start]
        while queue:
            c, r = queue.pop(0)
            if (c, r) == self.exit:
                return True
            for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c + dc, r + dr)
                if n in seen or self.wall(*n) or self.grid[n[1]][n[0]] == "O":
                    continue
                seen.add(n)
                queue.append(n)
        return False


def cell_center(col, row):
    return (GRID_X + col * CELL + CELL / 2, GRID_Y + row * CELL + CELL / 2)


def tilt_vector(inputs, zero):
    """Calibrated (tx, ty) in mg from the raw acceleration and a zero baseline."""
    raw = (inputs["ax"], inputs["ay"], inputs["az"])
    tx = raw[TILT_AXIS_X] - zero[TILT_AXIS_X]
    ty = raw[TILT_AXIS_Y] - zero[TILT_AXIS_Y]
    if INVERT_TILT_X:
        tx = -tx
    if INVERT_TILT_Y:
        ty = -ty
    return tx, ty


def _shape(value, dead, full):
    """Dead zone then linear ramp to +-1."""
    if abs(value) < dead:
        return 0.0
    sign = 1 if value > 0 else -1
    return sign * min(1.0, (abs(value) - dead) / (full - dead))


class Game:
    def __init__(self, levels=LEVELS, best=0):
        self.levels = [Level(spec) for spec in levels]
        self.best = best
        self.mode = MODE_READY
        self.level_index = 0
        self.lives = START_LIVES
        self.score = 0
        self.now = 0.0
        self.zero = (0, 0, 0)
        self.x, self.y = cell_center(*self.levels[0].start)
        self.vx = self.vy = 0.0
        self.level_started = 0.0
        self.level_time_used = 0.0
        self.mode_since = 0.0
        self.tilt = (0.0, 0.0)
        self.level_loaded = -1        # tells main.py when to send the grid
        self._prev_buttons = 0
        self._first = True
        self._last_update = None
        self._resume_mode = MODE_PLAYING
        self._paused_time_used = 0.0

    # ----- properties ---------------------------------------------------

    @property
    def level(self):
        return self.levels[self.level_index]

    def time_left(self):
        return max(0.0, self.level.time_limit - self.level_time_used)

    # ----- update -------------------------------------------------------

    def update(self, now, inputs):
        self.now = now
        dt = 0.0 if self._last_update is None else min(MAX_DT, max(0.0, now - self._last_update))
        self._last_update = now
        buttons = inputs["buttons"]
        connected = inputs["connected"]
        if self._first:
            self._prev_buttons = buttons
            self._first = False
        new = buttons & ~self._prev_buttons
        self._prev_buttons = buttons

        has_control = connected & (CONN_MOVEMENT | CONN_JOYSTICK)
        if not has_control:
            self._pause()
            return
        if self.mode == MODE_PAUSED:
            self._resume()

        self.tilt = self._control(inputs, connected)

        if self.mode == MODE_READY:
            if new & B and connected & CONN_MOVEMENT:
                self._zero(inputs)
            if new & STICK or (new & A and not connected & CONN_JOYSTICK):
                if connected & CONN_MOVEMENT:
                    self._zero(inputs)
                self._begin_run()
        elif self.mode == MODE_PLAYING:
            self._physics(dt)
            self.level_time_used += dt
            self._check_cells()
            if self.mode == MODE_PLAYING and self.time_left() <= 0:
                self._game_over()
        elif self.mode == MODE_CLEAR:
            if now - self.mode_since >= CLEAR_PAUSE:
                self._next_level()
        elif self.mode == MODE_RESULT:
            if now - self.mode_since >= RESULT_COOLDOWN and \
                    (new & STICK or (new & A and not connected & CONN_JOYSTICK)):
                self._set_mode(MODE_READY)

    def _control(self, inputs, connected):
        """Normalized (-1..1, -1..1) steering from tilt, or the stick as fallback."""
        if connected & CONN_MOVEMENT:
            tx, ty = tilt_vector(inputs, self.zero)
            return (_shape(tx, TILT_DEAD_ZONE_MG, TILT_MAX_MG),
                    _shape(ty, TILT_DEAD_ZONE_MG, TILT_MAX_MG))
        x = -inputs["x"] if INVERT_STICK_X else inputs["x"]
        y = -inputs["y"] if INVERT_STICK_Y else inputs["y"]
        return (_shape(x, JOYSTICK_DEAD_ZONE, 127), _shape(y, JOYSTICK_DEAD_ZONE, 127))

    def _zero(self, inputs):
        self.zero = (inputs["ax"], inputs["ay"], inputs["az"])

    # ----- physics ------------------------------------------------------

    def _physics(self, dt):
        if dt <= 0:
            return
        sx, sy = self.tilt
        self.vx += sx * ACCEL_PX * dt
        self.vy += sy * ACCEL_PX * dt
        damp = math.exp(-DAMPING * dt)
        self.vx *= damp
        self.vy *= damp
        speed = math.hypot(self.vx, self.vy)
        if speed > MAX_SPEED:
            self.vx *= MAX_SPEED / speed
            self.vy *= MAX_SPEED / speed
        # Substep so the ball never tunnels through a 24 px wall.
        steps = max(1, int(math.ceil(speed * dt / (CELL / 2))))
        for _ in range(steps):
            self._move_axis(self.vx * dt / steps, 0)
            self._move_axis(0, self.vy * dt / steps)

    def _collides(self, x, y):
        left = int((x - BALL_R - GRID_X) // CELL)
        right = int((x + BALL_R - 0.001 - GRID_X) // CELL)
        top = int((y - BALL_R - GRID_Y) // CELL)
        bottom = int((y + BALL_R - 0.001 - GRID_Y) // CELL)
        for col in range(left, right + 1):
            for row in range(top, bottom + 1):
                if self.level.wall(col, row):
                    return True
        return False

    def _move_axis(self, dx, dy):
        nx, ny = self.x + dx, self.y + dy
        if not self._collides(nx, ny):
            self.x, self.y = nx, ny
            return
        # Slide up to the wall in 1 px steps, then stop that axis.
        step_x = 0 if dx == 0 else (1 if dx > 0 else -1)
        step_y = 0 if dy == 0 else (1 if dy > 0 else -1)
        for _ in range(int(abs(dx) + abs(dy)) + 1):
            tx, ty = self.x + step_x, self.y + step_y
            if self._collides(tx, ty):
                break
            self.x, self.y = tx, ty
        if dx:
            self.vx = 0.0
        if dy:
            self.vy = 0.0

    def _check_cells(self):
        col = int((self.x - GRID_X) // CELL)
        row = int((self.y - GRID_Y) // CELL)
        if (col, row) == self.level.exit:
            self._level_clear()
            return
        for hole in self.level.holes:
            hx, hy = cell_center(*hole)
            if math.hypot(self.x - hx, self.y - hy) < HOLE_R:
                self._fall()
                return

    # ----- flow ---------------------------------------------------------

    def _set_mode(self, mode):
        self.mode = mode
        self.mode_since = self.now

    def _begin_run(self):
        self.lives = START_LIVES
        self.score = 0
        self.level_index = 0
        self._load_level()
        self._set_mode(MODE_PLAYING)

    def _load_level(self):
        self.x, self.y = cell_center(*self.level.start)
        self.vx = self.vy = 0.0
        self.level_time_used = 0.0
        self.level_loaded = -1   # main.py sends the grid, then sets this

    def _respawn(self):
        self.x, self.y = cell_center(*self.level.start)
        self.vx = self.vy = 0.0

    def _fall(self):
        self.lives -= 1
        if self.lives <= 0:
            self.lives = 0
            self._game_over()
            return
        self._respawn()

    def _level_clear(self):
        bonus = 100 + int(self.time_left())
        self.score += bonus
        self.last_bonus = bonus
        self.best = max(self.best, self.score)
        self._set_mode(MODE_CLEAR)

    def _next_level(self):
        if self.level_index + 1 >= len(self.levels):
            self._set_mode(MODE_RESULT)
            self.won = True
            return
        self.level_index += 1
        self._load_level()
        self._set_mode(MODE_PLAYING)

    def _game_over(self):
        self.won = False
        self.best = max(self.best, self.score)
        self._set_mode(MODE_RESULT)

    def _pause(self):
        if self.mode == MODE_PAUSED:
            return
        self._resume_mode = self.mode
        self._set_mode(MODE_PAUSED)

    def _resume(self):
        self._set_mode(self._resume_mode)
        self.vx = self.vy = 0.0
        self._prev_buttons = 0

    # ----- output -------------------------------------------------------

    def frame(self, connected):
        """(mode, x, y, level, lives, time_pct, score, best, connected, extra)

        extra: in READY the tilt-test marker offset packed as (mx+50)*101+(my+50)
        with mx, my in -50..50; in CLEAR the bonus just earned; in RESULT 1 if
        the run was won.
        """
        pct = 0
        if self.mode in (MODE_PLAYING, MODE_PAUSED):
            pct = int(round(100 * self.time_left() / self.level.time_limit))
        extra = 0
        if self.mode == MODE_READY:
            mx = int(round(self.tilt[0] * 50))
            my = int(round(self.tilt[1] * 50))
            extra = (mx + 50) * 101 + (my + 50)
        elif self.mode == MODE_CLEAR:
            extra = getattr(self, "last_bonus", 0)
        elif self.mode == MODE_RESULT:
            extra = 1 if getattr(self, "won", False) else 0
        return (
            int(self.mode),
            int(max(0, min(479, round(self.x)))),
            int(max(0, min(319, round(self.y)))),
            int(self.level_index + 1),
            int(max(0, min(START_LIVES, self.lives))),
            int(max(0, min(100, pct))),
            int(max(0, min(99999, self.score))),
            int(max(0, min(99999, self.best))),
            int(connected & 7),
            int(max(0, min(99999, extra))),
        )
