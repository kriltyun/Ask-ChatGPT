#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python -m venv .venv
.venv/bin/python -m pip install --cache-dir /workspace/.cache/pip -r requirements.txt
npm ci --cache /workspace/.npm --no-audit --no-fund
npm run build
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
npm test
