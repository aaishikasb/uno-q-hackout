import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import maze  # noqa: E402
from maze import (A, B, STICK, CELL, COLS, ROWS, GRID_X, GRID_Y,  # noqa: E402
                  CONN_BUTTONS, CONN_JOYSTICK, CONN_MOVEMENT,
                  MODE_CLEAR, MODE_PAUSED, MODE_PLAYING, MODE_READY, MODE_RESULT,
                  Game, Level, LEVELS, cell_center)

ALL = CONN_BUTTONS | CONN_JOYSTICK | CONN_MOVEMENT
FLAT = {"ax": 50, "ay": -75, "az": 1034}


def inputs(buttons=0, connected=ALL, tx=0, ty=0, x=0, y=0):
    """Snapshot with a game-direction tilt of (tx, ty) mg relative to FLAT.

    Positive tx rolls the ball right, positive ty rolls it down the screen,
    whatever the mounting inversion constants are set to."""
    raw = [FLAT["ax"], FLAT["ay"], FLAT["az"]]
    raw[maze.TILT_AXIS_X] += -tx if maze.INVERT_TILT_X else tx
    raw[maze.TILT_AXIS_Y] += -ty if maze.INVERT_TILT_Y else ty
    return {"connected": connected, "buttons": buttons, "x": x, "y": y,
            "ax": raw[0], "ay": raw[1], "az": raw[2], "video": 0}


TINY = {"time": 10, "grid": [
    "####################",
    "#S.E...............#",
    "#..................#",
    "#O.................#",
    "#..................#",
    "#..................#",
    "#..................#",
    "#..................#",
    "#..................#",
    "#..................#",
    "####################",
]}


OPEN = {"time": 30, "grid": [
    "####################",
    "#S.......#........E#",
    "#..................#",
] + ["#..................#"] * 7 + ["####################"]}


class LevelTests(unittest.TestCase):
    def test_all_levels_well_formed_and_solvable(self):
        for i, spec in enumerate(LEVELS):
            with self.subTest(level=i + 1):
                level = Level(spec)
                self.assertEqual(len(level.wire()), COLS * ROWS)
                self.assertTrue(level.solvable())
                self.assertTrue(all(level.wall(c, 0) and level.wall(c, ROWS - 1)
                                    for c in range(COLS)))
                self.assertTrue(all(level.wall(0, r) and level.wall(COLS - 1, r)
                                    for r in range(ROWS)))

    def test_levels_get_harder(self):
        holes = [len(Level(s).holes) for s in LEVELS]
        self.assertEqual(holes, sorted(holes))
        self.assertEqual(holes[0], 0)
        self.assertEqual(holes, [0, 3, 5])
        self.assertEqual([Level(s).start for s in LEVELS], [(1, 1)] * 3)
        self.assertEqual([Level(s).exit for s in LEVELS], [(17, 9)] * 3)


class GameTests(unittest.TestCase):
    def setUp(self):
        self.g = Game()
        self.t = 0.0

    def tick(self, snap, dt=0.05):
        self.t += dt
        self.g.update(self.t, snap)

    def start(self, connected=ALL):
        self.tick(inputs(0, connected))
        self.tick(inputs(STICK, connected))
        self.tick(inputs(0, connected))
        self.assertEqual(self.g.mode, MODE_PLAYING)

    def test_ready_then_stick_starts_and_zeroes_tilt(self):
        self.assertEqual(self.g.mode, MODE_READY)
        # Console held at an odd angle while starting: that angle becomes level.
        self.tick(inputs(0, tx=200, ty=-150))
        self.tick(inputs(STICK, tx=200, ty=-150))
        self.assertEqual(self.g.mode, MODE_PLAYING)
        self.tick(inputs(0, tx=200, ty=-150))
        self.assertEqual(self.g.tilt, (0.0, 0.0))
        self.assertEqual(self.g.level_index, 0)
        self.assertEqual(self.g.lives, 3)
        self.assertEqual(self.g.level_loaded, -1)

    def test_b_rezeroes_in_ready(self):
        self.tick(inputs(0, tx=300))
        self.assertGreater(self.g.tilt[0], 0)
        self.tick(inputs(B, tx=300))
        self.tick(inputs(0, tx=300))
        self.assertEqual(self.g.tilt, (0.0, 0.0))

    def test_ready_marker_encodes_tilt(self):
        self.tick(inputs(0))
        self.tick(inputs(B))          # zero at the flat position first
        self.tick(inputs(0, tx=1000, ty=-1000))
        frame = self.g.frame(ALL)
        extra = frame[-1]
        mx, my = extra // 101 - 50, extra % 101 - 50
        self.assertEqual((mx, my), (50, -50))

    def test_tilt_right_rolls_ball_right_and_wall_stops_it(self):
        self.g = Game(levels=[OPEN])
        self.start()
        x0 = self.g.x
        for _ in range(10):
            self.tick(inputs(0, tx=300))
        self.assertGreater(self.g.x, x0)
        for _ in range(200):
            self.tick(inputs(0, tx=400))
        # OPEN row 1 is floor from col 1 to col 8; col 9 is a wall.
        wall_left_edge = GRID_X + 9 * CELL
        self.assertLessEqual(self.g.x + maze.BALL_R, wall_left_edge)
        self.assertGreater(self.g.x, wall_left_edge - CELL)
        self.assertEqual(self.g.vx, 0.0)
        self.assertEqual(self.g.mode, MODE_PLAYING)

    def test_no_tilt_no_motion(self):
        self.start()
        x0, y0 = self.g.x, self.g.y
        for _ in range(20):
            self.tick(inputs(0, tx=10, ty=-10))   # inside the dead zone
        self.assertEqual((self.g.x, self.g.y), (x0, y0))

    def test_hole_costs_a_life_and_respawns(self):
        self.g = Game(levels=[TINY])
        self.start()
        for _ in range(100):
            self.tick(inputs(0, ty=350))
            if self.g.lives < 3:
                break
        self.assertEqual(self.g.lives, 2)
        self.assertEqual((self.g.x, self.g.y), cell_center(1, 1))
        self.assertEqual(self.g.mode, MODE_PLAYING)

    def test_three_falls_end_the_run(self):
        self.g = Game(levels=[TINY])
        self.start()
        for _ in range(400):
            self.tick(inputs(0, ty=350))
            if self.g.mode == MODE_RESULT:
                break
        self.assertEqual(self.g.mode, MODE_RESULT)
        self.assertEqual(self.g.lives, 0)
        self.assertFalse(self.g.won)

    def test_exit_clears_level_and_last_level_wins(self):
        self.g = Game(levels=[TINY, TINY])
        self.start()
        for _ in range(100):
            self.tick(inputs(0, tx=350))
            if self.g.mode == MODE_CLEAR:
                break
        self.assertEqual(self.g.mode, MODE_CLEAR)
        self.assertGreaterEqual(self.g.score, 100)
        self.assertEqual(self.g.frame(ALL)[-1], self.g.last_bonus)
        self.tick(inputs(0), dt=maze.CLEAR_PAUSE + 0.1)
        self.assertEqual(self.g.mode, MODE_PLAYING)
        self.assertEqual(self.g.level_index, 1)
        self.assertEqual((self.g.x, self.g.y), cell_center(1, 1))
        for _ in range(100):
            self.tick(inputs(0, tx=350))
            if self.g.mode == MODE_CLEAR:
                break
        self.tick(inputs(0), dt=maze.CLEAR_PAUSE + 0.1)
        self.assertEqual(self.g.mode, MODE_RESULT)
        self.assertTrue(self.g.won)
        self.assertEqual(self.g.frame(ALL)[-1], 1)
        self.assertEqual(self.g.best, self.g.score)

    def test_timeout_ends_the_run(self):
        self.g = Game(levels=[TINY])
        self.start()
        for _ in range(int(TINY["time"] / maze.MAX_DT) + 5):
            self.tick(inputs(0), dt=maze.MAX_DT)
        self.assertEqual(self.g.mode, MODE_RESULT)
        self.assertFalse(self.g.won)

    def test_result_restarts_after_cooldown(self):
        self.g = Game(levels=[TINY])
        self.start()
        for _ in range(400):
            self.tick(inputs(0, ty=350))
            if self.g.mode == MODE_RESULT:
                break
        self.tick(inputs(STICK), dt=0.1)
        self.assertEqual(self.g.mode, MODE_RESULT)   # too soon
        self.tick(inputs(0), dt=1.0)
        self.tick(inputs(STICK), dt=0.1)
        self.assertEqual(self.g.mode, MODE_READY)

    def test_joystick_fallback_when_movement_missing(self):
        conn = CONN_BUTTONS | CONN_JOYSTICK
        self.start(conn)
        x0 = self.g.x
        for _ in range(10):
            self.tick(inputs(0, conn, x=120))
        self.assertGreater(self.g.x, x0)

    def test_a_starts_when_joystick_missing(self):
        conn = CONN_BUTTONS | CONN_MOVEMENT
        self.tick(inputs(0, conn))
        self.tick(inputs(A, conn))
        self.assertEqual(self.g.mode, MODE_PLAYING)

    def test_pause_when_no_steering_control(self):
        self.start()
        used = self.g.level_time_used
        self.tick(inputs(0, CONN_BUTTONS))
        self.assertEqual(self.g.mode, MODE_PAUSED)
        self.tick(inputs(0, CONN_BUTTONS), dt=5)
        self.assertEqual(self.g.level_time_used, used)
        self.tick(inputs(0, ALL))
        self.assertEqual(self.g.mode, MODE_PLAYING)

    def test_frame_is_ten_bounded_ints(self):
        self.start()
        frame = self.g.frame(ALL)
        self.assertEqual(len(frame), 10)
        self.assertTrue(all(type(v) is int for v in frame))
        mode, x, y, level, lives, pct, score, best, connected, extra = frame
        self.assertEqual((mode, level, lives, pct, connected), (MODE_PLAYING, 1, 3, 100, ALL))
        self.assertTrue(0 <= x < 480 and GRID_Y <= y < 320)


if __name__ == "__main__":
    unittest.main()
