"""Map validated hardware input to a display preview; replace this with game rules."""

DEAD_ZONE = 26
INVERT_X = False
INVERT_Y = True
MOVEMENT_ZERO_MG = (-15, -994, 13)
MOVEMENT_DEAD_ZONE_MG = 20


def calibrated(inputs):
    """Validate one snapshot; return (x, y, pressed, ax, ay, az, connected)."""
    limits = {
        "connected": (0, 7), "buttons": (0, 15),
        "x": (-127, 128), "y": (-127, 128),
        "ax": (-16000, 16000), "ay": (-16000, 16000), "az": (-16000, 16000),
    }
    for key, (low, high) in limits.items():
        value = inputs[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Invalid arcade input: {key}")

    connected = inputs["connected"]
    x = inputs["x"] if connected & 2 else 0
    y = inputs["y"] if connected & 2 else 0
    x = 0 if abs(x) < DEAD_ZONE else x
    y = 0 if abs(y) < DEAD_ZONE else y
    if INVERT_X:
        x = -x
    if INVERT_Y:
        y = -y
    pressed = inputs["buttons"] & ((7 if connected & 1 else 0) | (8 if connected & 2 else 0))
    acceleration = []
    for key, zero in zip(("ax", "ay", "az"), MOVEMENT_ZERO_MG):
        delta = inputs[key] - zero if connected & 4 else 0
        acceleration.append(0 if abs(delta) < MOVEMENT_DEAD_ZONE_MG
                            else max(-16000, min(16000, delta)))
    return (x, y, pressed, *acceleration, connected)


def frame_values(inputs):
    x, y, pressed, ax, ay, az, connected = calibrated(inputs)
    return (
        max(20, min(460, 240 + round(x * 220 / 128))),
        max(168, min(300, 234 + round(y * 66 / 128))),
        pressed, ax, ay, az, connected,
    )
