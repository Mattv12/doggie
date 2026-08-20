# HoundMind systemd deployment

This unit runs HoundMind as `root`, matching the working PiDog hardware context.
It conflicts with `pidog-gpt.service`, so never run both services at once.

Do not install or enable it until the selected HoundMind configuration has passed
the hardware test.

```bash
sudo install -m 0644 deploy/systemd/houndmind.service /etc/systemd/system/houndmind.service
sudo install -m 0600 deploy/systemd/houndmind.env.example /etc/doggie/houndmind.env
sudo systemctl daemon-reload
sudo systemctl start houndmind.service
```

To return to the current Doggie runtime:

```bash
sudo systemctl stop houndmind.service
sudo systemctl start pidog-gpt.service
```
