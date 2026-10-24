import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


PYTHON = Path(__file__).resolve().parents[1] / "python"
INPUTS = {"connected": 7, "buttons": 0, "x": 0, "y": 0,
          "ax": 50, "ay": -75, "az": 1034, "video": 0}


class GameLoopTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Mock()
        self.output = self.enterContext(patch("builtins.print"))
        app_utils = SimpleNamespace(App=Mock(), Bridge=self.bridge)
        with patch.dict(sys.modules, {"arduino.app_utils": app_utils}), \
                patch.object(sys, "path", [str(PYTHON), *sys.path]):
            self.loop = runpy.run_path(str(PYTHON / "main.py"))["loop"]
        self.sleep = Mock()
        self.clock = [100.0]
        self.loop.__globals__["time"] = SimpleNamespace(
            sleep=self.sleep, monotonic=lambda: self.clock[0])
        self.output.reset_mock()

    def calls(self):
        return [c.args for c in self.bridge.call.call_args_list]

    def test_first_loop_reads_then_draws_and_returned_inputs_feed_next_loop(self):
        self.bridge.call.return_value = json.dumps(INPUTS)
        self.loop()
        names = [c[0] for c in self.calls()]
        # The first loop also preloads maze 1 so the sketch has it before play.
        self.assertEqual(names, ["arcade_read_inputs", "arcade_maze_load", "arcade_maze_frame"])
        frame = self.calls()[2][1:]
        self.assertEqual(len(frame), 10)
        self.assertTrue(all(type(v) is int for v in frame))
        self.assertEqual(frame[0], 0)   # MODE_READY
        self.bridge.reset_mock()
        self.clock[0] += 0.05
        self.loop()
        names = [c[0] for c in self.calls()]
        self.assertEqual(names, ["arcade_maze_frame"])   # no separate read
        self.output.assert_not_called()

    def test_bytes_responses_accepted(self):
        for response in (json.dumps(INPUTS).encode(), bytearray(json.dumps(INPUTS).encode())):
            with self.subTest(type=type(response).__name__):
                self.bridge.reset_mock()
                self.bridge.call.return_value = response
                self.loop()
                self.assertEqual(self.calls()[-1][0], "arcade_maze_frame")

    def test_stick_press_loads_level_then_draws(self):
        self.bridge.call.return_value = json.dumps(INPUTS)
        self.loop()
        self.bridge.reset_mock()
        self.clock[0] += 0.05
        self.bridge.call.return_value = json.dumps({**INPUTS, "buttons": 8})
        self.loop()
        self.bridge.reset_mock()
        self.clock[0] += 0.05
        self.bridge.call.return_value = json.dumps(INPUTS)
        self.loop()
        names = [c[0] for c in self.calls()]
        self.assertEqual(names, ["arcade_maze_load", "arcade_maze_frame"])
        grid = self.calls()[0][1]
        self.assertIsInstance(grid, bytes)
        self.assertEqual(len(grid), 20 * 11)
        self.assertIn(b"S", grid)
        self.assertEqual(self.calls()[1][1], 1)   # MODE_PLAYING
        self.bridge.reset_mock()
        self.clock[0] += 0.05
        self.loop()
        self.assertEqual([c[0] for c in self.calls()], ["arcade_maze_frame"])

    def test_invalid_responses_recover_on_next_loop(self):
        for response in (None, 7, {}, [], "not JSON", "[]", "{}",
                         json.dumps({**INPUTS, "buttons": 99}),
                         json.dumps({**INPUTS, "ax": "50"})):
            with self.subTest(response=response):
                self.bridge.reset_mock()
                self.bridge.call.return_value = response
                self.loop()
                self.sleep.assert_called_with(1)
                self.assertTrue(self.output.call_args.args[0].startswith(
                    "Arcade connection/input error:"))
                self.bridge.reset_mock()
                self.bridge.call.return_value = json.dumps(INPUTS)
                self.loop()
                self.assertEqual(self.calls()[-1][0], "arcade_maze_frame")

    def test_video_owner_suspends_game(self):
        self.bridge.call.return_value = json.dumps({**INPUTS, "video": 1})
        self.loop()
        self.assertEqual([c[0] for c in self.calls()], ["arcade_read_inputs"])
        self.sleep.assert_called_once_with(0.5)
        self.output.assert_not_called()


if __name__ == "__main__":
    unittest.main()
