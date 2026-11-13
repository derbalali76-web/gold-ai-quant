#!/usr/bin/env bash
# GOLD AI QUANT - Linux/Mac
set -e
cd "$(dirname "$0")/backend"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
exec python -m uvicorn --factory goldquant.api:create_app --host 0.0.0.0 --port 8000
