"""Custom Doggie configuration.

Values here should stay simple and easy to tune on the Pi.
"""

BATTERY_WARN_VOLTAGE = 7.0
BATTERY_LOW_VOLTAGE = 6.8
BATTERY_CRITICAL_VOLTAGE = 6.5

DEFAULT_ACTION_SPEED = 70
DEFAULT_REST_SPEED = 75

POWER_PROFILES = {
    "boot": {
        "rgb_mode": "breath",
        "rgb_color": "blue",
        "rgb_bps": 0.6,
        "rgb_brightness": 0.35,
        "rest_action": None,
        "movement_allowed": False,
        "sound_allowed": False,
    },
    "active": {
        "rgb_mode": "listen",
        "rgb_color": "cyan",
        "rgb_bps": 0.8,
        "rgb_brightness": 0.55,
        "rest_action": None,
        "movement_allowed": True,
        "sound_allowed": True,
    },
    "idle": {
        "rgb_mode": "breath",
        "rgb_color": "green",
        "rgb_bps": 0.35,
        "rgb_brightness": 0.2,
        "rest_action": "sit",
        "movement_allowed": True,
        "sound_allowed": False,
    },
    "sleep": {
        "rgb_mode": "off",
        "rgb_color": "black",
        "rgb_bps": 0.2,
        "rgb_brightness": 0.0,
        "rest_action": "lie",
        "movement_allowed": True,
        "sound_allowed": False,
    },
    "low_battery": {
        "rgb_mode": "off",
        "rgb_color": "black",
        "rgb_bps": 0.2,
        "rgb_brightness": 0.0,
        "rest_action": "lie",
        "movement_allowed": False,
        "sound_allowed": False,
    },
}

