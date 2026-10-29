#!/bin/sh
set -e
python -m pip install --no-cache-dir -r requirements.txt
exec python bot.py
