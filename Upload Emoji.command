#!/bin/bash
# Double-click this file (Mac) to upload a folder of emoji to Slack.
cd "$(dirname "$0")" || exit 1

pause() { echo; read -r -p "Press Enter to close this window..." _; }

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
  echo "This tool needs Python 3, which isn't installed yet."
  echo "Opening the Python download page. Install it, then double-click this file again."
  open "https://www.python.org/downloads/"
  pause; exit 1
fi

VENV=".venv"
if ! "$VENV/bin/python" -c 'import requests, PIL' >/dev/null 2>&1; then
  echo "First-time setup: installing what this tool needs (about a minute)..."
  python3 -m venv "$VENV" &&
    "$VENV/bin/python" -m pip install --quiet --disable-pip-version-check requests pillow
  if [ $? -ne 0 ]; then
    echo; echo "Setup failed. Check your internet connection and try again."
    pause; exit 1
  fi
  echo "Done."
fi

"$VENV/bin/python" upload.py "$@"
pause
