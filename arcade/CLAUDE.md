# Level Devil on UNO Q
- Game: Level Devil, a trap platformer on Arduino UNO Q. TFT is 480x320 landscape, tiles 32px, grid 15x10.
- Bridge.call is a synchronous RPC at 115200 baud, max 256 bytes per call. Never redraw the full screen per frame; redraw only dirty tiles, and batch several draw commands into one call.
- Inputs: x/y are -127..128, dead zone 26 in python/preview.py frame_values. buttons bitmask: A=1, B=2, C=4, stick press=8. Always check inputs["connected"] before using a control.
- Controls: joystick X = move, Button A = jump (edge-triggered), Button C = restart.
- Clamp and validate every RPC argument in the sketch.
- Physics uses fixed 1/60s substeps so fast falls can't tunnel through floors.
- Do not modify retroarch/. Deploy with make flash, Python logs with make logs, MCU serial with make monitor.
- Keep the starter working until the replacement is proven. Commit-sized changes only.
