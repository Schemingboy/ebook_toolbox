#!/usr/bin/env bash
# ebook_toolbox launcher for macOS / Linux.
#
# ASCII-only on purpose, mirroring start.cmd: all human-facing text lives in
# bootstrap.py so there is exactly one place to maintain it.
set -euo pipefail

cd "$(dirname "$0")"

PYEXE=""

# Prefer the project venv when it is already there.
if [ -x ".venv/bin/python" ]; then
    PYEXE=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYEXE="python3"
elif command -v python >/dev/null 2>&1; then
    PYEXE="python"
fi

if [ -z "$PYEXE" ]; then
    cat <<'EOF'

  Python not found.

  Install Python 3.11 or newer:
    macOS:  brew install python
    Ubuntu: sudo apt install python3 python3-venv

  Then run this script again.

EOF
    exit 1
fi

exec "$PYEXE" bootstrap.py "$@"
