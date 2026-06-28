#!/usr/bin/env bash
#
# Agnes Investor Desk - one-command launcher.
#
# Make sure GEMINI_API_KEY is set in .env, then:
#   ./run.sh
#   PORT=8080 ./run.sh
#
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-3005}"

if curl -sf "http://localhost:${PORT}/api/health" >/dev/null 2>&1; then
  echo "[ok] Agnes already running at http://localhost:${PORT}"
  exit 0
fi

echo "-> Starting Agnes on http://localhost:${PORT}"
exec .venv/bin/python web/app.py --port "${PORT}"
