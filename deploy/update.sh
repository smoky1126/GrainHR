#!/bin/bash
# Replace the open-source code and restart GrainHR. Company files stay on the server.
set -euo pipefail
ROOT="${GRAINHR_ROOT:-$HOME/GrainHR}"
archive="$(mktemp)"
unpack="$(mktemp -d)"
trap 'rm -rf "$archive" "$unpack"' EXIT
# GRAINHR_REF is a version tag, for example v1.6.0. The script does not install main.
ref="${GRAINHR_REF:?Set GRAINHR_REF to a version tag, for example v1.6.0}"
case "$ref" in
  v*) ;;
  *) echo "GRAINHR_REF must be a version tag such as v1.6.0" >&2; exit 1 ;;
esac
curl -fsSL -o "$archive" "https://github.com/smoky1126/GrainHR/archive/refs/tags/${ref}.tar.gz"
tar -xzf "$archive" -C "$unpack"
src="$(find "$unpack" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
find "$src" -mindepth 1 -maxdepth 1 ! -name .venv ! -name .streamlit -exec cp -a {} "$ROOT"/ \;
# A folder named pages makes Streamlit replace the Chinese menu with file names.
rm -rf "$ROOT/app/pages"
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
sudo systemctl restart grainhr
echo "GrainHR restarted."
