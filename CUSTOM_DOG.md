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
chmod +x scripts/doggie_reboot.sh
chmod +x scripts/doggie_git_check.sh
```

The GPT voice service must be installed from the current
`examples/deploy/pidog-gpt.service`. It now starts only after `doggie-boot`
has finished, which prevents both services from initializing the PiDog
controller at once during a cold boot.

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
journalctl -b -u doggie-boot.service --no-pager
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
sudo python3 -m custom_dog.main prepare-reboot
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

For a remote reboot that asks the dog to sit first, use:

```bash
sudo /home/matt/pidog/scripts/doggie_reboot.sh
```

Or from your Windows terminal:

```bash
ssh matt@raspberrypi "sudo /home/matt/pidog/scripts/doggie_reboot.sh"
```

For a quick git communication check before remote deploys, use:

```bash
sudo /home/matt/pidog/scripts/doggie_git_check.sh
```

Or from your Windows terminal:

```bash
ssh matt@raspberrypi "sudo /home/matt/pidog/scripts/doggie_git_check.sh"
```

## Tuning Boot

The service accepts these environment variables:

- `DOGGIE_REPO_DIR`: repo path, default `/home/matt/pidog`
- `DOGGIE_REPO_OWNER`: repo owner used for `git pull`, default detected from the repo directory
- `DOGGIE_BRANCH`: branch to pull, default `main`
- `DOGGIE_NETWORK_TIMEOUT`: seconds to wait for internet, default `20`
- `DOGGIE_PULL_TIMEOUT`: seconds allowed for `git pull`, default `25`
- `DOGGIE_START_DELAY`: extra seconds to wait before touching PiDog hardware, default `8`
- `DOGGIE_BOOT_RETRIES`: how many times to retry `custom_dog.main boot` if startup fails, default `3`
- `DOGGIE_BOOT_RETRY_DELAY`: seconds to wait between boot retries, default `5`
- `DOGGIE_BOOT_ARGS`: extra args for `custom_dog.main boot`

Example:

```ini
Environment=DOGGIE_BOOT_ARGS=--sound
```

For the most battery-efficient boot, use:

```ini
Environment=DOGGIE_BOOT_ARGS=--profile sleep
```

If the Pi is reachable but doggie still does not come up after reboot, run:

```bash
sudo systemctl status doggie-boot.service
journalctl -b -u doggie-boot.service --no-pager
systemctl is-enabled doggie-boot.service
sudo python3 -m custom_dog.main status --battery
```

If SSH drops with `client_loop: send disconnect: Connection reset`, that usually
points to a Pi-side power, Wi-Fi, or reboot problem rather than a Python import
error. Also check:

```bash
sudo journalctl -b -1 -n 120 --no-pager
dmesg -T | tail -n 80
vcgencmd get_throttled
```

If the Pi cannot be reached at all, connect a monitor/keyboard and run this
local recovery check before changing Wi-Fi credentials:

```bash
nmcli device status
nmcli connection show
sudo rfkill unblock wifi
sudo nmcli device set wlan0 managed yes
sudo nmcli device connect wlan0
```

`bin/pidog_app_install.sh` deliberately configures `wlan0` as the `pidog`
hotspot (and disables its normal Wi-Fi client). Do not run it on this setup;
if it was run, restore the normal Wi-Fi configuration before expecting the Pi
to join a home network.

## Temporary Head Safety Lock

When hardware behind the head needs protection, set this in the
`pidog-gpt.service` unit and restart the service:

```ini
Environment=DOGGIE_HEAD_MOTION_ENABLED=0
```

This blocks all head servo commands, including automatic animations and preset
actions. While locked, Doggie holds its head level when sitting and about five
degrees down when standing or lying. Set it back to `1` only after the physical
clearance issue is fixed.

## Local Face and Guard Retention

Doggie keeps all camera, face, and guard data on the Pi. Owner enrollment
samples in `/home/matt/.pidog_faces/owner` remain until you explicitly remove
them. Guard snapshots and non-owner face crops are kept locally for 60 days,
then removed automatically while guard mode is running. They are stored in:

- `/home/matt/pidog/guard_photos`
- `/home/matt/.pidog_faces/visitors`

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
