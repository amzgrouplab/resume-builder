#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-/opt/homebrew/bin/python3.11}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON="python3"
fi

if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q -r backend/requirements.txt

echo "Vellum is opening at http://127.0.0.1:8000"
python -m uvicorn app.main:app --app-dir backend --reload --reload-dir backend/app --host 127.0.0.1 --port 8000
