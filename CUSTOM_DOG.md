# Custom Doggie

This repo keeps the stock SunFounder `pidog` package mostly intact and puts our
custom behavior in `custom_dog/`.

## First Goal

Fast boot:

1. Raspberry Pi OS connects to Wi-Fi.
2. `doggie-boot.service` starts.
3. `scripts/doggie_boot.sh` waits briefly for internet.
4. If online, it pulls the latest `main` from GitHub.
5. It launches `python3 -m custom_dog.main boot`.

If internet is not ready, the dog still starts local code instead of waiting
forever.

## Power Strategy

Battery life is handled with simple power profiles in `custom_dog/config.py`.
This keeps the dog from doing expensive work unless we ask for it.

Current profiles:

- `boot`: low-brightness light feedback, no movement by default
- `active`: normal action mode for explicit commands
- `idle`: sit with dim light feedback
- `sleep`: lie down and turn lights off
- `low_battery`: lie down and block optional movement

The first HoundMind ideas we are adopting are modular config, opt-in heavy
features, battery thresholds, quiet/rest modes, and low-cost defaults. We are
not importing its full runtime yet because that would add a lot of moving parts
before our boot and battery behavior are proven on this dog.

## Pi Install

Run this on the PiDog:

```bash
cd /home/matt/pidog
git pull origin main
chmod +x scripts/doggie_boot.sh
sudo cp examples/deploy/doggie-boot.service /etc/systemd/system/doggie-boot.service
sudo systemctl daemon-reload
sudo systemctl enable doggie-boot.service
sudo systemctl start doggie-boot.service
```

For GPT voice mode secrets, use a root-owned environment file instead of
`secret.py`:

```bash
sudo install -d -m 700 /etc/doggie
sudo install -m 600 examples/deploy/pidog-gpt.env.example /etc/doggie/pidog-gpt.env
sudoedit /etc/doggie/pidog-gpt.env
sudo cp examples/deploy/pidog-gpt.service /etc/systemd/system/pidog-gpt.service
sudo systemctl daemon-reload
sudo systemctl restart pidog-gpt
```

Check it:

```bash
sudo systemctl status doggie-boot.service
journalctl -u doggie-boot.service -n 80 --no-pager
```

## Manual Commands

From `/home/matt/pidog` on the Pi:

```bash
sudo python3 -m custom_dog.main status
sudo python3 -m custom_dog.main status --battery
sudo python3 -m custom_dog.main boot
sudo python3 -m custom_dog.main boot --profile sleep
sudo python3 -m custom_dog.main boot --sound
sudo python3 -m custom_dog.main boot --stand
sudo python3 -m custom_dog.main idle
sudo python3 -m custom_dog.main sleep
sudo python3 -m custom_dog.main profile active
sudo python3 -m custom_dog.main action sit
sudo python3 -m custom_dog.main action bark
sudo python3 -m custom_dog.main action wag-tail
sudo python3 -m custom_dog.main respond "sit down"
sudo python3 -m custom_dog.main respond "what's your battery"
sudo python3 -m custom_dog.main listen
```

If the battery is low, movement commands are blocked unless you deliberately
add `--force`:

```bash
sudo python3 -m custom_dog.main action sit --force
```

## Tuning Boot

The service accepts these environment variables:

- `DOGGIE_REPO_DIR`: repo path, default `/home/matt/pidog`
- `DOGGIE_REPO_OWNER`: repo owner used for `git pull`, default detected from the repo directory
- `DOGGIE_BRANCH`: branch to pull, default `main`
- `DOGGIE_NETWORK_TIMEOUT`: seconds to wait for internet, default `20`
- `DOGGIE_PULL_TIMEOUT`: seconds allowed for `git pull`, default `25`
- `DOGGIE_BOOT_ARGS`: extra args for `custom_dog.main boot`

Example:

```ini
Environment=DOGGIE_BOOT_ARGS=--sound
```

For the most battery-efficient boot, use:

```ini
Environment=DOGGIE_BOOT_ARGS=--profile sleep
```

## Companion Mode

`custom_dog.main` now has a lightweight custom companion layer for fast testing.
It does not require the full upstream GPT voice assistant stack.

- `respond "..."` parses a phrase into speech and actions once
- `listen` starts a simple interactive loop from the terminal
- low battery still blocks movement-heavy commands

Examples:

```bash
sudo python3 -m custom_dog.main respond "hello doggie"
sudo python3 -m custom_dog.main respond "move forward"
sudo python3 -m custom_dog.main listen
```
