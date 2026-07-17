#!/usr/bin/env python3
"""Custom PiDog command runner.

This is the place for our own behavior code. Keep the stock ``pidog`` package
close to upstream and add custom routines here.
"""

from __future__ import annotations

import argparse
import socket
import sys
from contextlib import contextmanager
from time import sleep

from pidog import Pidog

from .companion import build_response, execute_plan
from .config import DEFAULT_ACTION_SPEED, POWER_PROFILES
from .power import apply_profile, choose_boot_profile, get_battery_state


ACTION_MAP = {
    "stand": ("action", "stand"),
    "sit": ("action", "sit"),
    "lie": ("action", "lie"),
    "wag-tail": ("action", "wag_tail"),
    "forward": ("action", "forward"),
    "backward": ("action", "backward"),
    "turn-left": ("action", "turn_left"),
    "turn-right": ("action", "turn_right"),
    "bark": ("sound", "single_bark_1"),
}


@contextmanager
def dog_session():
    dog = Pidog()
    try:
        yield dog
    finally:
        dog.close()


def has_internet(host: str = "github.com", port: int = 443, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def boot(args: argparse.Namespace) -> int:
    online = has_internet()

    with dog_session() as dog:
        battery = get_battery_state(dog)
        profile_name = args.profile or choose_boot_profile(online, battery)
        profile = apply_profile(dog, profile_name, rest=False)

        if args.sound and profile["sound_allowed"]:
            dog.speak("single_bark_1", volume=args.volume)
        if args.stand and profile["movement_allowed"]:
            dog.do_action("stand", speed=DEFAULT_ACTION_SPEED)
            dog.wait_all_done()
        else:
            sleep(args.pause)

    voltage = "unknown" if battery.voltage is None else f"{battery.voltage:.2f}v"
    print(
        "doggie boot complete: "
        f"internet={'yes' if online else 'no'} "
        f"profile={profile_name} battery={battery.level} voltage={voltage}"
    )
    return 0


def run_action(args: argparse.Namespace) -> int:
    action_type, value = ACTION_MAP[args.name]

    with dog_session() as dog:
        battery = get_battery_state(dog)
        if battery.is_low and not args.force:
            print(f"battery {battery.level}; blocked action '{args.name}' without --force")
            apply_profile(dog, "low_battery", rest=True)
            return 2

        apply_profile(dog, "active", rest=False)
        if action_type == "sound":
            dog.speak(value, volume=args.volume)
            sleep(args.pause)
        else:
            dog.do_action(value, step_count=args.steps, speed=args.speed)
            dog.wait_all_done()

    return 0


def run_profile(args: argparse.Namespace) -> int:
    with dog_session() as dog:
        battery = get_battery_state(dog)
        if battery.is_low and args.name not in {"low_battery", "sleep"} and not args.force:
            print(f"battery {battery.level}; using low_battery profile")
            apply_profile(dog, "low_battery", rest=True)
            return 2

        apply_profile(dog, args.name, rest=args.rest)
        print(f"profile={args.name} battery={battery.level}")

    return 0


def idle(args: argparse.Namespace) -> int:
    args.name = "idle"
    args.rest = True
    return run_profile(args)


def sleep_mode(args: argparse.Namespace) -> int:
    args.name = "sleep"
    args.rest = True
    return run_profile(args)


def status(args: argparse.Namespace) -> int:
    online = has_internet()
    message = f"internet={'yes' if online else 'no'}"

    if args.battery:
        with dog_session() as dog:
            battery = get_battery_state(dog)
        voltage = "unknown" if battery.voltage is None else f"{battery.voltage:.2f}v"
        message += f" battery={battery.level} voltage={voltage}"

    print(message)
    return 0


def respond(args: argparse.Namespace) -> int:
    with dog_session() as dog:
        battery = get_battery_state(dog)
        plan = build_response(args.text, battery)
        execute_plan(
            dog,
            plan,
            action_speed=args.speed,
            rest_speed=args.speed,
            volume=args.volume,
        )

    if plan.speech:
        print(plan.speech)
    if plan.actions:
        print(f"actions={','.join(plan.actions)}")
    return 0


def listen(args: argparse.Namespace) -> int:
    print("doggie listener ready; type commands and press Enter. Type 'quit' to stop.")
    while True:
        try:
            text = input("doggie> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0

        with dog_session() as dog:
            battery = get_battery_state(dog)
            plan = build_response(text, battery)
            execute_plan(
                dog,
                plan,
                action_speed=args.speed,
                rest_speed=args.speed,
                volume=args.volume,
            )

        if plan.speech:
            print(plan.speech)
        if plan.actions:
            print(f"actions={','.join(plan.actions)}")
        if plan.stop:
            return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Custom PiDog command runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    boot_parser = subparsers.add_parser("boot", help="safe startup routine")
    boot_parser.add_argument("--sound", action="store_true", help="play a short bark")
    boot_parser.add_argument("--stand", action="store_true", help="stand after boot")
    boot_parser.add_argument("--profile", choices=sorted(POWER_PROFILES))
    boot_parser.add_argument("--pause", type=float, default=1.5)
    boot_parser.add_argument("--volume", type=int, default=70)
    boot_parser.set_defaults(func=boot)

    action_parser = subparsers.add_parser("action", help="run a basic action")
    action_parser.add_argument("name", choices=sorted(ACTION_MAP))
    action_parser.add_argument("--steps", type=int, default=1)
    action_parser.add_argument("--speed", type=int, default=70)
    action_parser.add_argument("--pause", type=float, default=1.0)
    action_parser.add_argument("--volume", type=int, default=80)
    action_parser.add_argument("--force", action="store_true", help="allow action on low battery")
    action_parser.set_defaults(func=run_action)

    profile_parser = subparsers.add_parser("profile", help="apply a power profile")
    profile_parser.add_argument("name", choices=sorted(POWER_PROFILES))
    profile_parser.add_argument("--rest", action="store_true", help="also move to the profile rest pose")
    profile_parser.add_argument("--force", action="store_true", help="allow non-rest profile on low battery")
    profile_parser.set_defaults(func=run_profile)

    idle_parser = subparsers.add_parser("idle", help="battery-friendly idle posture")
    idle_parser.add_argument("--force", action="store_true", help="allow idle on low battery")
    idle_parser.set_defaults(func=idle)

    sleep_parser = subparsers.add_parser("sleep", help="lowest-power resting posture")
    sleep_parser.add_argument("--force", action="store_true", help="accepted for command consistency")
    sleep_parser.set_defaults(func=sleep_mode)

    status_parser = subparsers.add_parser("status", help="check basic runtime status")
    status_parser.add_argument("--battery", action="store_true", help="also read PiDog battery voltage")
    status_parser.set_defaults(func=status)

    respond_parser = subparsers.add_parser("respond", help="parse text into custom dog behavior")
    respond_parser.add_argument("text", help="command or phrase for the dog")
    respond_parser.add_argument("--speed", type=int, default=DEFAULT_ACTION_SPEED)
    respond_parser.add_argument("--volume", type=int, default=80)
    respond_parser.set_defaults(func=respond)

    listen_parser = subparsers.add_parser("listen", help="interactive custom command loop")
    listen_parser.add_argument("--speed", type=int, default=DEFAULT_ACTION_SPEED)
    listen_parser.add_argument("--volume", type=int, default=80)
    listen_parser.set_defaults(func=listen)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
