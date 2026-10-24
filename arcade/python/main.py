import time

from arduino.app_utils import App, Bridge
from levdevil import Game

game = Game(Bridge)
last = time.monotonic()

# Timing accumulators (reset every second).
_t_read = _t_tick = _t_loop = 0.0
_frames = 0
_report_at = time.monotonic()


def loop():
    global last, _t_read, _t_tick, _t_loop, _frames, _report_at
    t0 = time.monotonic()
    try:
        t1 = time.monotonic()
        inputs = game.exchange()  # Draws the last frame and reads the controls in one call.
        _t_read += time.monotonic() - t1

        if inputs.get("video", 0):
            time.sleep(0.5)
            return

        now = time.monotonic()
        t2 = time.monotonic()
        game.tick(inputs, min(now - last, 0.05))
        _t_tick += time.monotonic() - t2
        last = now
    except Exception as error:
        # A failed call may leave a half-drawn screen, so redraw everything next time.
        print(f"Arcade connection/input error: {error}")
        game.drawn = None
        game.cmds = []
        time.sleep(1)
        return

    _t_loop += time.monotonic() - t0
    _frames += 1

    now = time.monotonic()
    if now - _report_at >= 1.0:
        elapsed = now - _report_at
        n = max(_frames, 1)
        print(
            f"fps={_frames / elapsed:.1f}  "
            f"bridge={1000 * _t_read / n:.1f}ms  "
            f"tick(draw)={1000 * _t_tick / n:.1f}ms  "
            f"loop={1000 * _t_loop / n:.1f}ms",
            flush=True,
        )
        _t_read = _t_tick = _t_loop = 0.0
        _frames = 0
        _report_at = now


print("Level Devil: stick to run, A to jump, C to restart the level.")
App.run(user_loop=loop)
