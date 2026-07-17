# RaceSpace PiDog

Custom brain for a SunFounder PiDog v2 (Raspberry Pi 5). GPT voice assistant
("hey doggie") with vision, plus a pile of behavior mods on top of the stock
`sunfounder/pidog` examples.

## Files

| File | What it is |
|---|---|
| `20_voice_active_dog_gpt.py` | Entry point: GPT config, wake words, personality prompt, action rules |
| `voice_active_dog.py` | The assistant: parallel startup, balance/watch modes, camera stream + low-light boost, battery sense, pivot turns hookup, crash guards |
| `dog_abilities.py` | AbilitiesMixin: head life (idle curiosity / wake arousal), guard mode, owner face recognition, fetch, pivot turns, sit gaze |
| `deploy/pidog-gpt.service` | systemd unit (runs as root, loads `/etc/doggie/pidog-gpt.env`, Restart=always) |
| `deploy/dog-deploy` | pull + syntax check + service restart, run via `ssh matt@10.0.0.55 dog-deploy` |

The GPT service no longer reads `secret.py`. Put runtime secrets in a root-owned
environment file on the Pi instead:

```bash
sudo install -d -m 700 /etc/doggie
sudo install -m 600 examples/deploy/pidog-gpt.env.example /etc/doggie/pidog-gpt.env
sudoedit /etc/doggie/pidog-gpt.env
```

Required values:

- `OPENAI_API_KEY`
- `OPENAI_MODEL` is optional and defaults to `gpt-4o-mini`

## Workflow

1. Edit anywhere (VS Code, laptop, wherever), commit, push.
2. `ssh matt@10.0.0.55 dog-deploy` — pulls, syntax-checks, restarts the dog.
3. Watch it: `ssh matt@10.0.0.55 dog-logs` (journal tail alias).

The live camera is at `http://10.0.0.55:8080/` while GPT mode is running.

## Notable hardware findings (hard-won, do not relearn)

- Touch pads are capacitive and need a ground reference: they only work
  reliably on USB power; on battery, touch the chassis with your other hand.
- Battery sense is ADC A5 (reg 0x12), not A4; the MCU only answers combined
  write+read I2C transactions (`read_battery()` uses smbus2 directly).
- The library's `set_rpy(pid=True)` pitch correction has an inverted sign on
  this dog — balance mode uses a custom PID (KP=0.033, don't raise it).
- Garage measures ~0.5 lux: the ov5647 maxes out (gain 8, 66ms), so frames
  get adaptive digital gain (`_brighten`, cap 4x) before streaming/vision.
