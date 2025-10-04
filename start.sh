#!/bin/bash
set -e

echo "==> Starting GXP MQTT Worker..."
cd gxp-mqtt-worker
python app.py
