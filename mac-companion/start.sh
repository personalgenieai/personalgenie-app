#!/bin/bash
# PersonalGenie Mac Companion — start script
# Run this from Terminal. Requires Full Disk Access for Terminal.

set -e
cd "$(dirname "$0")"

# Check for .env
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from template."
    echo "Open mac-companion/.env and add your ANTHROPIC_API_KEY, then re-run this script."
    echo ""
    open .env
    exit 1
  fi
fi

# Install deps if needed
if ! python3 -c "import fastapi, anthropic, uvicorn" 2>/dev/null; then
  echo "Installing dependencies..."
  pip3 install -q -r requirements.txt
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   PersonalGenie Mac Companion            ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Starting on port 5001..."
echo "Make sure Terminal has Full Disk Access in:"
echo "  System Settings → Privacy & Security → Full Disk Access"
echo ""

python3 server.py
