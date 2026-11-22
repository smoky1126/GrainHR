#!/bin/bash
# One-time packages for the GrainHR server. Run as a user who can sudo.
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip rclone cloudflared \
  libreoffice-writer libreoffice-calc fonts-noto-cjk
sudo mkdir -p /srv/grainhr/hr /opt/grainhr
sudo chown -R "$USER:$USER" /srv/grainhr /opt/grainhr
if [ ! -d /opt/grainhr/.git ]; then
  git clone https://github.com/smoky1126/GrainHR.git /opt/grainhr
fi
python3 -m venv /opt/grainhr/.venv
/opt/grainhr/.venv/bin/pip install -U pip
/opt/grainhr/.venv/bin/pip install -r /opt/grainhr/requirements.txt
echo "Next: copy rclone.conf, company.toml, and .streamlit/secrets.toml. See deploy/README.md."
