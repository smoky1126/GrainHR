#!/bin/bash
# Replace the open-source code and restart GrainHR. Company files stay on the server.
set -euo pipefail
ROOT="${GRAINHR_ROOT:-$HOME/GrainHR}"
archive="$(mktemp)"
unpack="$(mktemp -d)"
trap 'rm -rf "$archive" "$unpack"' EXIT
curl -fsSL -o "$archive" https://github.com/smoky1126/GrainHR/archive/refs/heads/main.tar.gz
tar -xzf "$archive" -C "$unpack"
src="$(find "$unpack" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
find "$src" -mindepth 1 -maxdepth 1 ! -name .venv ! -name .streamlit -exec cp -a {} "$ROOT"/ \;
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
sudo systemctl restart grainhr
echo "GrainHR restarted."
