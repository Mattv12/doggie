# Voice Setup and Live Diagnosis

The Pi 4/5 vision configuration enables voice with short, forgiving commands.
It uses SpeechRecognition initially, which needs an internet connection for
Google transcription. For dependable offline recognition, switch to Vosk after
the microphone is confirmed working.

## Watch live logs

On Doggie, use one of these while speaking a command:

```bash
sudo journalctl -u houndmind.service -f
# Or, when started manually:
tail -F /home/matt/houndmind/logs/houndmind.log
```

Healthy operation reports `SpeechRecognition STT started`, then `Voice heard:`
and `Voice command ->`. An initialization error means the microphone or its
Python audio dependency is unavailable; a `service error` means Google speech
recognition cannot reach the internet.

## Select the microphone

```bash
cd /home/matt/houndmind
source .venv/bin/activate
python -m tools.list_audio_devices
```

Set the desired input number in
`settings.pi5-vision.json` at
`settings.voice_assistant.stt.device_index`, then restart HoundMind. Leave it
as `null` to use the system default.

## Commands to try

Speak one short command at a time: `sit`, `stand`, `go`, `go ahead`, `come
here`, `go back`, `left`, `right`, `wag`, or `stop`. Saying `Doggie` or `Hey
Doggie` first is optional. Set `require_wake_word` to `true` if background
conversation causes false commands.

## Quick command-path test

This bypasses the microphone and proves that actions are reaching the runtime:

```bash
python -m tools.voice_cli say --text "doggie sit"
```

To use this, temporarily set `voice_assistant.http.enabled` to `true` and keep
its host at `127.0.0.1`; run the command on Doggie itself.
