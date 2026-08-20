#!/usr/bin/env bash
# Keep the first Doggie TTS playback on one known-good audio route.  The
# Bluetooth/PulseAudio session is user-owned and may come up after systemd.
set -euo pipefail

readonly WAIT_SECONDS="${DOGGIE_AUDIO_WAIT_SECONDS:-45}"
readonly PULSE_RUNTIME="${XDG_RUNTIME_DIR:-/run/user/1000}"
readonly PULSE_COOKIE="${PULSE_COOKIE:-/home/matt/.config/pulse/cookie}"
export PULSE_SERVER="${PULSE_SERVER:-unix:${PULSE_RUNTIME}/pulse/native}"
export PULSE_COOKIE

deadline=$((SECONDS + WAIT_SECONDS))
until pactl info >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "Doggie audio bootstrap: PulseAudio did not become ready." >&2
    exit 1
  fi
  sleep 1
done

# Start voice in body-speaker/USB-microphone mode. This removes a stale
# combine sink left by a previous Bluetooth session, which could otherwise
# duplicate the opening TTS audio on the body speaker.
/usr/local/sbin/doggie-headset-audio disable
sleep 1
