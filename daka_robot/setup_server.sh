#!/bin/bash
# One-time setup for the DAKA emulator on andrew.
# Stop immediately when /dev/kvm is missing: a software-only emulator is too slow.
set -euo pipefail
if [ ! -e /dev/kvm ]; then
  echo "先在 LXD 宿主機執行："
  echo "  lxc config device add <容器名稱> kvm unix-char path=/dev/kvm"
  echo "然後在這個容器內："
  echo "  sudo usermod -aG kvm ubuntu"
  echo "容器內的主機名稱是 $(hostname)。請在宿主機用 lxc list 核對容器名稱。"
  exit 1
fi
sudo apt-get update
sudo apt-get install -y openjdk-17-jre-headless unzip wget
SDK="$HOME/android-sdk"
mkdir -p "$SDK/cmdline-tools"
if [ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]; then
  tmp="$(mktemp -d)"
  wget -q -O "$tmp/cmd.zip" https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  unzip -q "$tmp/cmd.zip" -d "$tmp"
  rm -rf "$SDK/cmdline-tools/latest"
  mkdir -p "$SDK/cmdline-tools/latest"
  mv "$tmp/cmdline-tools/"* "$SDK/cmdline-tools/latest/"
  rm -rf "$tmp"
fi
export ANDROID_SDK_ROOT="$SDK"
yes | "$SDK/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null || true
"$SDK/cmdline-tools/latest/bin/sdkmanager" "platform-tools" "emulator" "system-images;android-34;google_apis_playstore;x86_64"
echo no | "$SDK/cmdline-tools/latest/bin/avdmanager" create avd -n daka -k "system-images;android-34;google_apis_playstore;x86_64" --device "pixel_6" || true
python3 -m venv "$HOME/daka-robot/.venv"
"$HOME/daka-robot/.venv/bin/pip" install -U pip uiautomator2
if [ -x "$HOME/daka-robot/saver/build_saver.sh" ]; then
  bash "$HOME/daka-robot/saver/build_saver.sh"
fi
echo "模擬器已建立。請用 scrcpy 登入一次，再填 steps.json，然後："
echo "  mkdir -p ~/.config/systemd/user"
echo "  cp ~/daka-robot/daka-robot.service ~/daka-robot/daka-robot.timer ~/.config/systemd/user/"
echo "  systemctl --user daemon-reload && systemctl --user enable --now daka-robot.timer"
