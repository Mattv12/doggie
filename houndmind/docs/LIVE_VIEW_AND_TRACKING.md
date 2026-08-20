# Live view and visual target tracking

Use `config/settings.pi5-vision.json` for Doggie's Pi 4/5 vision runtime. It
publishes a LAN-only visual feed and a visual-only target lock: it does not
issue a motor, navigation, or follow command.

## Open the camera

Put the phone/laptop and Doggie on the same Wi-Fi, then open either address:

- `http://doggie.local:8090/` — camera only, usually the simplest option.
- `http://doggie.local:8092/` — camera plus telemetry and target-lock state.

If the `.local` name is unavailable, run this **on Doggie** and use the first
address it prints instead:

```bash
hostname -I
```

For example, if it prints `192.168.1.42`, use
`http://192.168.1.42:8090/`. Do not forward ports 8090, 8092, or 8088 from the
internet; these endpoints are intended for the trusted local network only.

## Install the detection model and start

The object model is intentionally not committed to the repository. On Doggie:

```bash
cd /home/matt/houndmind
source .venv/bin/activate
python -m tools.download_opencv_models
python -m houndmind_ai --config config/settings.pi5-vision.json
```

If HoundMind runs as `houndmind.service`, set `HOUNDMIND_CONFIG` in
`/etc/doggie/houndmind.env` to `/home/matt/houndmind/config/settings.pi5-vision.json`,
then restart it:

```bash
sudo systemctl restart houndmind.service
sudo journalctl -u houndmind.service -n 80 --no-pager
```

Look for `Vision HTTP stream` and `semantic_status`/`face_recognition_status`
messages. If the model files are missing or OpenCV is not installed, semantic
labeling disables itself and the target state remains `searching`.

## What lock states mean

- `searching` — no accepted person/animal is visible.
- `acquiring` — a detection is being confirmed across frames.
- `body_locked` — a person or supported animal was stably detected.
- `face_locked` — a detected face falls within a locked person box; its label
  is the enrolled name or `unknown`.

For reliable name matching, enroll each consenting person with several clear,
front-facing views. Enable the local-only face HTTP endpoint temporarily,
then run `python -m tools.face_recognition_cli enroll --name NAME` repeatedly
while the person is centered in view. Disable that endpoint again afterwards.
