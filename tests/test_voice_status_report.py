import sys
from pathlib import Path


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

from voice_active_dog import VoiceActiveDog  # noqa: E402


def test_status_report_query_patterns():
    assert VoiceActiveDog._is_status_report_query("What network are you connected to?")
    assert VoiceActiveDog._is_status_report_query("Give me a battery status")
    assert not VoiceActiveDog._is_status_report_query("Sit down")


def test_status_report_contains_network_and_battery():
    dog = VoiceActiveDog.__new__(VoiceActiveDog)
    dog._get_network_status = lambda: {
        "connected": "yes",
        "internet": True,
        "ssid": "mattsinternet",
        "signal": 84,
        "ip": "10.0.0.55",
    }
    dog.read_battery = lambda: (7.8, 67.0)

    report = dog._build_status_report_reply()

    assert "mattsinternet" in report
    assert "84 percent" in report
    assert "10.0.0.55" in report
    assert "67.0 percent" in report
    assert report.endswith("ACTIONS:")


def test_offline_reply_is_useful_and_has_no_action_text_for_tts():
    dog = VoiceActiveDog.__new__(VoiceActiveDog)
    reply = dog._build_offline_reply("what can you do")

    assert "offline" in reply.lower()
    assert "sit" in reply.lower()
    assert reply.endswith("ACTIONS:")


def test_direct_actions_match_words_not_substrings():
    assert VoiceActiveDog._direct_action_for_text("sit down") == "sit"
    assert VoiceActiveDog._direct_action_for_text("I understand") is None


def test_startup_announcement_reports_online_network_and_battery():
    dog = VoiceActiveDog.__new__(VoiceActiveDog)
    dog._get_network_status = lambda: {
        "connected": "yes",
        "internet": True,
        "ssid": "mattsinternet",
        "signal": 84,
        "ip": "10.0.0.55",
    }
    dog.read_battery = lambda: (7.8, 67.0)

    announcement = dog._build_startup_announcement()

    assert announcement.startswith("Doggie is ready.")
    assert "online on mattsinternet" in announcement
    assert "67.0 percent" in announcement


def test_startup_announcement_distinguishes_wifi_from_internet():
    dog = VoiceActiveDog.__new__(VoiceActiveDog)
    dog._get_network_status = lambda: {
        "connected": "yes",
        "internet": False,
        "ssid": "mattsinternet",
        "signal": 84,
        "ip": "10.0.0.55",
    }
    dog.read_battery = lambda: (None, None)

    announcement = dog._build_startup_announcement()

    assert "connected to mattsinternet" in announcement
    assert "no internet access" in announcement
    assert "online" not in announcement


def test_visual_question_is_honest_when_camera_is_unavailable():
    dog = VoiceActiveDog.__new__(VoiceActiveDog)
    dog.with_image = False
    dog.picam2 = None

    reply = dog.think("What can you see?")

    assert "can't see" in reply
    assert "camera is unavailable" in reply
    assert reply.endswith("ACTIONS:")
