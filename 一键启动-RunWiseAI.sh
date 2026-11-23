#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if command -v python3.12 >/dev/null 2>&1; then PYTHON=python3.12;
elif command -v python3 >/dev/null 2>&1; then PYTHON=python3;
else echo '请先安装 Python 3.12 或 3.13' >&2; exit 1; fi
"$PYTHON" tools/launch_runwise.py
