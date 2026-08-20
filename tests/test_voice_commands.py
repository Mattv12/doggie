from houndmind_ai.optional.voice import VoiceModule


def test_short_commands_and_wake_word_are_normalized():
    voice = VoiceModule("voice")
    settings = {"wake_words": ["doggie", "hey doggie"], "require_wake_word": False}
    assert voice._prepare_command("Hey Doggie, turn left!", settings) == "turn left"
    assert voice._resolve_action("go ahead", {"go ahead": "forward"}, {}) == "forward"


def test_wake_word_can_be_required():
    voice = VoiceModule("voice")
    settings = {"wake_words": ["doggie"], "require_wake_word": True}
    assert voice._prepare_command("sit", settings) is None
    assert voice._prepare_command("doggie sit", settings) == "sit"
