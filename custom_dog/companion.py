"""Lightweight custom companion behavior for PiDog.

This keeps command handling simple and local so we can test the dog's
responses without depending on the full upstream voice assistant stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .power import BatteryState, apply_profile


ACTION_ALIASES = {
    "sit": ("sit", "sit down", "set"),
    "stand": ("stand", "stand up", "get up", "wake up"),
    "lie": ("lie", "lie down", "lay down", "rest", "sleep"),
    "wag-tail": ("wag tail", "wag", "tail"),
    "bark": ("bark", "woof"),
    "forward": ("forward", "go forward", "move forward", "walk forward"),
    "backward": ("backward", "back up", "move backward", "reverse"),
    "turn-left": ("turn left",),
    "turn-right": ("turn right",),
}

MOVEMENT_ACTIONS = {"stand", "sit", "lie", "forward", "backward", "turn-left", "turn-right"}
SOUND_EFFECTS = {"bark": "single_bark_1"}


@dataclass(frozen=True)
class ResponsePlan:
    speech: str = ""
    actions: list[str] = field(default_factory=list)
    profile: str | None = None
    rest: bool = False
    stop: bool = False


def normalize_text(text: str) -> str:
    cleaned = " ".join(text.lower().strip().split())
    return cleaned.replace("doggy", "doggie")


def build_response(text: str, battery: BatteryState) -> ResponsePlan:
    normalized = normalize_text(text)
    if not normalized:
        return ResponsePlan(speech="I did not catch that. Try a short command.")

    if normalized in {"quit", "exit", "stop listening"}:
        return ResponsePlan(speech="Standing by.", stop=True, profile="idle", rest=True)

    if "battery" in normalized or "charge" in normalized or "power" in normalized:
        return ResponsePlan(speech=_battery_line(battery))

    if normalized in {"hello", "hi", "hey doggie", "hey dog"}:
        return ResponsePlan(speech="I'm here. Tell me what to do.", actions=["wag-tail"])

    if "status" in normalized:
        mood = "low battery mode" if battery.is_low else "ready mode"
        return ResponsePlan(speech=f"I'm in {mood}. {_battery_line(battery)}")

    if "help" in normalized or "what can you do" in normalized:
        return ResponsePlan(
            speech=(
                "Try sit, stand, lie down, wag tail, bark, move forward, move backward, "
                "turn left, turn right, sleep, or ask about my battery."
            )
        )

    if normalized in {"sleep", "go to sleep", "good night"}:
        return ResponsePlan(speech="Going to sleep.", profile="sleep", rest=True)

    if normalized in {"idle", "settle down", "stand by", "standby"}:
        return ResponsePlan(speech="Settling in.", profile="idle", rest=True)

    actions = _detect_actions(normalized)
    if actions:
        if battery.is_low and any(action in MOVEMENT_ACTIONS for action in actions):
            return ResponsePlan(
                speech=f"My battery is {battery.level}, so I'm staying put. Use a sound command or charge me first.",
                profile="low_battery",
                rest=True,
            )
        return ResponsePlan(actions=actions, profile="active")

    if "good dog" in normalized or "thank" in normalized:
        return ResponsePlan(speech="Happy to help.", actions=["wag-tail"])

    if "who are you" in normalized:
        return ResponsePlan(speech="I'm Doggie, your custom PiDog copilot.")

    return ResponsePlan(speech="I heard you, but I need a clearer command. Try help if you want examples.")


def execute_plan(dog: Any, plan: ResponsePlan, *, action_speed: int, rest_speed: int, volume: int) -> None:
    if plan.profile:
        apply_profile(dog, plan.profile, rest=plan.rest)

    if plan.speech:
        _safe_speak(dog, plan.speech, volume=volume)

    for action in plan.actions:
        if action in SOUND_EFFECTS:
            _safe_speak(dog, SOUND_EFFECTS[action], volume=volume)
            continue
        _safe_action(dog, action, speed=action_speed)

    _safe_wait(dog)


def _detect_actions(normalized: str) -> list[str]:
    found: list[str] = []
    for action, aliases in ACTION_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            found.append(action)
    if "turn around" in normalized:
        found = ["turn-left", "turn-left"]
    return found[:2]


def _battery_line(battery: BatteryState) -> str:
    if battery.voltage is None:
        return f"Battery state is {battery.level}."
    return f"Battery is {battery.level} at {battery.voltage:.2f} volts."


def _safe_speak(dog: Any, value: str, *, volume: int) -> None:
    try:
        dog.speak(value, volume=volume)
    except Exception as exc:
        print(f"doggie speak warning: {exc}")


def _safe_action(dog: Any, action: str, *, speed: int) -> None:
    try:
        dog.do_action(action.replace("-", "_"), speed=speed)
    except Exception as exc:
        print(f"doggie action warning ({action}): {exc}")


def _safe_wait(dog: Any) -> None:
    try:
        dog.wait_all_done()
    except Exception as exc:
        print(f"doggie wait warning: {exc}")
