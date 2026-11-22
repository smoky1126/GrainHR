#!/bin/bash
# Pull the open-source code and restart GrainHR. Company files are not in git.
set -euo pipefail
cd /opt/grainhr
git pull --ff-only
.venv/bin/pip install -r requirements.txt
systemctl --user restart grainhr
echo "GrainHR restarted."
