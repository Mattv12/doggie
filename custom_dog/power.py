"""Power helpers for battery-efficient PiDog behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import (
    BATTERY_CRITICAL_VOLTAGE,
    BATTERY_LOW_VOLTAGE,
    BATTERY_WARN_VOLTAGE,
    DEFAULT_REST_SPEED,
    POWER_PROFILES,
)


@dataclass(frozen=True)
class BatteryState:
    voltage: float | None
    level: str

    @property
    def is_low(self) -> bool:
        return self.level in {"low", "critical"}


def get_battery_state(dog: Any) -> BatteryState:
    try:
        voltage = float(dog.get_battery_voltage())
    except Exception:
        return BatteryState(voltage=None, level="unknown")

    if voltage <= BATTERY_CRITICAL_VOLTAGE:
        level = "critical"
    elif voltage <= BATTERY_LOW_VOLTAGE:
        level = "low"
    elif voltage <= BATTERY_WARN_VOLTAGE:
        level = "warn"
    else:
        level = "ok"

    return BatteryState(voltage=round(voltage, 2), level=level)


def get_profile(name: str) -> dict[str, Any]:
    try:
        return POWER_PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(POWER_PROFILES))
        raise ValueError(f"unknown power profile '{name}'. Choices: {choices}") from exc


def apply_profile(dog: Any, name: str, *, rest: bool = False) -> dict[str, Any]:
    profile = get_profile(name)
    apply_rgb(dog, profile)

    rest_action = profile.get("rest_action")
    if rest and rest_action:
        dog.do_action(rest_action, speed=DEFAULT_REST_SPEED)
        dog.wait_all_done()

    return profile


def apply_rgb(dog: Any, profile: dict[str, Any]) -> None:
    if not hasattr(dog, "rgb_strip"):
        return

    mode = profile.get("rgb_mode", "off")
    color = profile.get("rgb_color", "black")
    bps = profile.get("rgb_bps", 0.3)
    brightness = profile.get("rgb_brightness", 0.2)

    if mode == "off":
        dog.rgb_strip.set_mode("breath", color="black", bps=0.2, brightness=0.0)
    else:
        dog.rgb_strip.set_mode(mode, color=color, bps=bps, brightness=brightness)


def choose_boot_profile(online: bool, battery: BatteryState) -> str:
    if battery.is_low:
        return "low_battery"
    return "boot" if online else "idle"
