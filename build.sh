#!/bin/bash
set -e

echo "==> Installing dependencies from gxp-mqtt-worker/"
pip install -r gxp-mqtt-worker/requirements.txt

echo "==> Build complete!"
