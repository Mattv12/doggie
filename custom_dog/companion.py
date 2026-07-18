"""Lightweight custom companion behavior for PiDog.

This keeps command handling simple and local so we can test the dog's
responses without depending on the full upstream voice assistant stack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from random import choice
from typing import Any

from pidog import Pidog
from pidog.preset_actions import surprise
from pidog.walk import Walk

from .power import BatteryState, apply_profile


ACTION_ALIASES = {
    "sit": ("sit", "sit down", "set"),
    "stand": ("stand", "stand up", "get up", "wake up"),
    "lie": ("lie", "lie down", "lay down", "rest", "sleep"),
    "wag-tail": ("wag tail", "wag", "tail"),
    "bark": ("bark", "woof"),
    "fart": ("fart", "take a poop right here", "poop right here", "take a poop"),
    "forward": ("forward", "go forward", "move forward", "walk forward"),
    "backward": ("backward", "back up", "move backward", "reverse"),
    "turn-left": ("turn left",),
    "turn-right": ("turn right",),
}
TRICK_ALIASES = {
    "turn-around": ("turn around", "spin around", "do a spin", "spin"),
    "rear-up": (
        "stand on two legs",
        "stand on your back legs",
        "stand on your rear legs",
        "rear up",
        "surprise me",
    ),
}

MOVEMENT_ACTIONS = {"stand", "sit", "lie", "forward", "backward", "turn-left", "turn-right"}
SOUND_EFFECTS = {"bark": "single_bark_1"}
MOVEMENT_TRICKS = {"turn-around", "rear-up"}
JOKE_PROMPTS = (
    "tell me a joke",
    "say a joke",
    "make me laugh",
    "do you know a joke",
    "can you tell me a joke",
)
JOKE_RESPONSES = (
    "Why did the robot dog sit in the shade? Because it did not want to overheat its paws.",
    "What do you call a dog that writes code? A bark end developer.",
    "Why was Doggie so calm? Because he had everything under paw control.",
    "What is a robot dog's favorite music? Anything with a good byte.",
    "Why did Doggie cross the room? To get to the other woof.",
    "What do you call a sleepy robot dog? A nap processor.",
    "Why did Doggie bring a ladder to the server rack? He heard the cloud was up there.",
    "What is Doggie's favorite snack? Microchips.",
    "Why was the robot dog such a good listener? He had excellent re-triever protocols.",
    "What did Doggie say after fixing the bug? That was ruff, but we got it.",
)


@dataclass(frozen=True)
class ResponsePlan:
    speech: str = ""
    actions: list[str] = field(default_factory=list)
    tricks: list[str] = field(default_factory=list)
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

    if normalized in {"hello", "hi", "hey doggie", "hey dog", "hello doggie", "hello dog"}:
        return ResponsePlan(speech="I'm here. Tell me what to do.", actions=["wag-tail"])
    if normalized.startswith(("hello", "hi", "hey")) and "dog" in normalized:
        return ResponsePlan(speech="I'm here. Tell me what to do.", actions=["wag-tail"])

    if "status" in normalized:
        mood = "low battery mode" if battery.is_low else "ready mode"
        return ResponsePlan(speech=f"I'm in {mood}. {_battery_line(battery)}")

    if "help" in normalized or "what can you do" in normalized:
        return ResponsePlan(
            speech=(
                "Try sit, stand, lie down, wag tail, bark, move forward, move backward, "
                "turn left, turn right, turn around, stand on two legs, fart, sleep, ask about my battery, or ask me for a joke."
            )
        )

    if _is_joke_request(normalized):
        return ResponsePlan(speech=choice(JOKE_RESPONSES), actions=["wag-tail"])

    if normalized in {"sleep", "go to sleep", "good night"}:
        return ResponsePlan(speech="Going to sleep.", profile="sleep", rest=True)

    if normalized in {"idle", "settle down", "stand by", "standby"}:
        return ResponsePlan(speech="Settling in.", profile="idle", rest=True)

    tricks = _detect_tricks(normalized)
    if tricks:
        if battery.is_low and any(trick in MOVEMENT_TRICKS for trick in tricks):
            return ResponsePlan(
                speech=f"My battery is {battery.level}, so I should skip that trick until I recharge.",
                profile="low_battery",
                rest=True,
            )
        return ResponsePlan(tricks=tricks, profile="active")

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

    for trick in plan.tricks:
        _safe_trick(dog, trick, speed=action_speed)

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
    return found[:2]


def _detect_tricks(normalized: str) -> list[str]:
    found: list[str] = []
    for trick, aliases in TRICK_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            found.append(trick)
    return found[:1]


def _is_joke_request(normalized: str) -> bool:
    if any(prompt in normalized for prompt in JOKE_PROMPTS):
        return True
    return "joke" in normalized and any(
        word in normalized for word in ("tell", "say", "know", "another", "funny", "laugh")
    )


def _battery_line(battery: BatteryState) -> str:
    if battery.voltage is None:
        return f"Battery state is {battery.level}."
    return f"Battery is {battery.level} at {battery.voltage:.2f} volts."


def _safe_speak(dog: Any, value: str, *, volume: int) -> None:
    tts = _get_tts()
    if tts is not None:
        try:
            if hasattr(tts, "say"):
                tts.say(value)
                return
        except Exception as exc:
            print(f"doggie tts warning: {exc}")
    try:
        dog.speak(value, volume=volume)
    except Exception as exc:
        print(f"doggie speak warning: {exc}")


def _safe_action(dog: Any, action: str, *, speed: int) -> None:
    try:
        if action == "fart":
            dog.speak("pant", volume=55)
            dog.do_action("wag_tail", step_count=1, speed=85)
            return
        dog.do_action(action.replace("-", "_"), speed=speed)
    except Exception as exc:
        print(f"doggie action warning ({action}): {exc}")


def _safe_trick(dog: Any, trick: str, *, speed: int) -> None:
    try:
        if trick == "turn-around":
            _pivot_turn(dog, cycles=8, speed=max(speed, 90))
        elif trick == "rear-up":
            surprise(dog, pitch_comp=0, status="stand")
    except Exception as exc:
        print(f"doggie trick warning ({trick}): {exc}")


def _safe_wait(dog: Any) -> None:
    try:
        dog.wait_all_done()
    except Exception as exc:
        print(f"doggie wait warning: {exc}")


@lru_cache(maxsize=2)
def _pivot_frames(side: str) -> list[list[float]]:
    if side == "left":
        scales = [-0.5, 1, -0.5, 1]
    else:
        scales = [1, -0.5, 1, -0.5]

    class _PivotWalk(Walk):
        LEG_STEP_SCALES = [scales, scales, scales]

    gait = _PivotWalk(Walk.FORWARD, Walk.LEFT)
    return [Pidog.legs_angle_calculation(coords) for coords in gait.get_coords()]


def _pivot_turn(dog: Any, *, cycles: int, speed: int) -> None:
    frames = _pivot_frames("left")
    for _ in range(cycles):
        dog.legs_move(frames, immediately=False, speed=speed)


@lru_cache(maxsize=1)
def _get_tts() -> Any | None:
    try:
        from pidog.tts import Espeak

        return Espeak()
    except Exception:
        return None
