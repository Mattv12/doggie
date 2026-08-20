# Doggie local web controller

The controller starts with the HoundMind service and works without internet.
On the same Wi-Fi network, open:

```text
http://doggie.local:8093/
```

It has a live camera background, a body D-pad, a head D-pad, and A/B/Y/Z
buttons. The current button actions are configured in
`settings.web_controller.buttons`; they can be changed without editing code.

`8093` is a dedicated controller port and does not interfere with the camera
(`8090`) or dashboard (`8092`). It is only reachable on Doggie's local network;
do not forward it to the internet.

## Stable address

Use a DHCP reservation in your router for Doggie's Wi-Fi MAC address. This is
the recommended way to keep an address such as `192.168.1.42` unchanged and it
does not interfere with other devices or broadcasts. The controller will then
always be `http://192.168.1.42:8093/`.

The `doggie.local` name is usually even easier. On Doggie, make its hostname
persistent and enable mDNS once:

```bash
sudo hostnamectl set-hostname doggie
sudo apt install -y avahi-daemon
sudo systemctl enable --now avahi-daemon
```

Restart HoundMind after the updated configuration is on Doggie:

```bash
sudo sed -i 's#^HOUNDMIND_CONFIG=.*#HOUNDMIND_CONFIG=/home/matt/houndmind/config/settings.pi5-vision.json#' /etc/doggie/houndmind.env
sudo systemctl restart houndmind.service
sudo journalctl -u houndmind.service -n 80 --no-pager
```

Look for `Web controller on http://0.0.0.0:8093/`.

## Chair false positives

Person locks now require a person-shaped, moving detection and a face inside
that body box. A static chair should remain `searching` or `acquiring_face`,
rather than becoming a locked person. Animals are still body-locked without a
face requirement.
