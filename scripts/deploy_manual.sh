#!/bin/bash
set -e

echo "Stopping PiDog scripts..."
sudo pkill -f 12_app_control.py || true
sudo pkill -f 20_voice_active_dog_gpt.py || true
sudo pkill -f voice_active_dog.py || true
sudo pkill -f 3_patrol.py || true

echo "Pulling latest code from GitHub..."
cd /home/matt/pidog
git pull origin main

echo "Starting manual app mode..."
cd /home/matt/pidog/examples
sudo python3 12_app_control.py
