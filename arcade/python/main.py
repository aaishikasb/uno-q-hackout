"""Tilt Maze on the UNO Q console.

One Bridge round trip per frame: `arcade_maze_frame` draws the ball and HUD
and returns the fresh input snapshot, so the loop runs about twice as fast
as a separate read + draw. The maze grid is sent once per level with
`arcade_maze_load`. The best score lives under `data/`, which `make flash`
keeps.
"""

import json
import time
from pathlib import Path

from arduino.app_utils import App, Bridge
from maze import Game

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
BEST_FILE = DATA_DIR / "best.json"

LIMITS = {
    "connected": (0, 7), "buttons": (0, 15),
    "x": (-127, 128), "y": (-127, 128),
    "ax": (-16000, 16000), "ay": (-16000, 16000), "az": (-16000, 16000),
}


def load_best():
    try:
        value = json.loads(BEST_FILE.read_text())["best"]
        return value if type(value) is int and 0 <= value <= 99999 else 0
    except Exception:
        return 0


def save_best(best):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        BEST_FILE.write_text(json.dumps({"best": best}))
    except Exception as error:
        print(f"Could not save best score: {error}")


def parse_inputs(response):
    if not isinstance(response, (str, bytes, bytearray)):
        raise TypeError("Expected JSON text from the sketch")
    inputs = json.loads(response)
    if not isinstance(inputs, dict):
        raise ValueError("Expected a JSON object")
    for key, (low, high) in LIMITS.items():
        value = inputs.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Invalid arcade input: {key}")
    return inputs


game = Game(best=load_best())
saved_best = game.best
pending = None   # input snapshot returned by the previous draw call


def loop():
    global pending, saved_best
    try:
        if pending is None:
            pending = parse_inputs(Bridge.call("arcade_read_inputs"))
        inputs = pending
        pending = None
        if inputs.get("video", 0):
            time.sleep(0.5)
            return
        game.update(time.monotonic(), inputs)
        if game.level_loaded != game.level_index:
            Bridge.call("arcade_maze_load", game.level.wire().encode())
            game.level_loaded = game.level_index
        pending = parse_inputs(
            Bridge.call("arcade_maze_frame", *game.frame(inputs["connected"])))
        if game.best > saved_best:
            saved_best = game.best
            save_best(saved_best)
    except Exception as error:
        # Without fresh frames the MCU clears the screen after 1.5 seconds.
        print(f"Arcade connection/input error: {error}")
        pending = None
        time.sleep(1)
        return
    time.sleep(0.01)


print("Tilt Maze: hold the console flat, press the stick, then tilt to roll.")
App.run(user_loop=loop)
