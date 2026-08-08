import sys
from pathlib import Path


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

from voice_active_dog import VoiceActiveDog  # noqa: E402


def test_web_command_allowlist_is_stationary_and_has_status():
    commands = VoiceActiveDog.WEB_COMMANDS

    assert commands["sit"] == "sit"
    assert commands["status report"] == "status report"
    assert "forward" not in commands
    assert "backward" not in commands
    assert "shell" not in commands
