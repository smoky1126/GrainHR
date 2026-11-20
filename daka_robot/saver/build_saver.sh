#!/bin/bash
# Build the tiny "DAKA Save" share target and install it on the emulator.
# It only writes the shared file into Downloads. It does not use the network.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
BT="$SDK/build-tools/34.0.0"
PLATFORM="$SDK/platforms/android-34/android.jar"
export PATH="$SDK/platform-tools:$PATH"
BUILD="$ROOT/build"
rm -rf "$BUILD"
mkdir -p "$BUILD/classes"
javac --release 17 -classpath "$PLATFORM" -d "$BUILD/classes" \
  "$ROOT/src/hk/example/dakasave/SaveActivity.java"
"$BT/d8" --min-api 29 --output "$BUILD" "$BUILD/classes/hk/example/dakasave/"*.class
"$BT/aapt2" link -o "$BUILD/unsigned.apk" --manifest "$ROOT/AndroidManifest.xml" \
  -I "$PLATFORM" --min-sdk-version 29 --target-sdk-version 34
python3 - "$BUILD" <<'PY'
import sys
import zipfile
from pathlib import Path
build = Path(sys.argv[1])
with zipfile.ZipFile(build / "unsigned.apk", "a") as apk:
    apk.write(build / "classes.dex", "classes.dex")
PY
"$BT/zipalign" -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"
KEYSTORE="$HOME/.android/daka-save.keystore"
mkdir -p "$HOME/.android"
if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -keystore "$KEYSTORE" -storepass android -keypass android \
    -alias save -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=DAKA Save"
fi
"$BT/apksigner" sign --ks "$KEYSTORE" --ks-pass pass:android \
  --key-pass pass:android --ks-key-alias save "$BUILD/aligned.apk"
if adb get-state >/dev/null 2>&1; then
  adb install -r "$BUILD/aligned.apk"
  echo SAVER_INSTALLED
else
  echo "APK 已建立。模擬器未開，稍後再安裝。"
fi
