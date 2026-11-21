#!/usr/bin/env bash
# Sheikh Arsalan Automation — Clip Studio
set -euo pipefail
cd "$(dirname "$0")"
PORT="${NEXCUT_PORT:-8137}"
echo "Sheikh Arsalan Automation — Clip Studio"
echo "open http://localhost:${PORT}   (Ctrl+C to stop)"
( sleep 1; command -v xdg-open >/dev/null && xdg-open "http://localhost:${PORT}" >/dev/null 2>&1 || \
  command -v open >/dev/null && open "http://localhost:${PORT}" >/dev/null 2>&1 || true ) &
exec python3 -m nexcut.server
