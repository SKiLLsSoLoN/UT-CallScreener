#!/bin/bash
# install.sh
# ──────────────────────────────────────────────────────────────────────────────
# Installs the Call Screener daemon on your Ubuntu Touch device.
# Run this on your DESKTOP (not the phone) with the phone connected via USB.
#
# Usage:  bash install.sh
# ──────────────────────────────────────────────────────────────────────────────

PHONE_USER="phablet"
INSTALL_DIR="/home/phablet/.local/share/callscreener"
AUDIO_DIR="$INSTALL_DIR/audio"
DAEMON_SCRIPT="daemon/callscreener_daemon.py"
UPSTART_CONF="daemon/callscreener-daemon.conf"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Call Screener — Device Installer  "
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check ADB
if ! command -v adb &> /dev/null; then
    echo "✗ adb not found — install android-tools-adb"
    exit 1
fi

echo "→ Checking device connection…"
adb wait-for-device
echo "✓ Device found"

# Create directories on phone
echo "→ Creating directories on device…"
adb shell "mkdir -p $INSTALL_DIR $AUDIO_DIR $INSTALL_DIR/recordings"

# Push daemon
echo "→ Pushing daemon script…"
adb push $DAEMON_SCRIPT $INSTALL_DIR/callscreener_daemon.py
adb shell "chmod +x $INSTALL_DIR/callscreener_daemon.py"

# Push WAV files (if they exist locally)
echo "→ Pushing WAV files…"
WAVS=(
    "assets/audio/greeting.wav"
    "assets/audio/call_you_back.wav"
    "assets/audio/what_calling.wav"
    "assets/audio/who_is_this.wav"
    "assets/audio/leave_message.wav"
    "assets/audio/not_interested.wav"
    "assets/audio/hold_on.wav"
)
for wav in "${WAVS[@]}"; do
    if [ -f "$wav" ]; then
        fname=$(basename "$wav")
        adb push "$wav" "$AUDIO_DIR/$fname"
        echo "  ✓ $fname"
    else
        echo "  ⚠ Missing: $wav  (add this WAV file before using)"
    fi
done

# Install pjsua2 Python bindings on device
echo "→ Installing Python dependencies on device…"
adb shell "sudo apt-get install -y python3-pjsua2 python3-dbus python3-gi || true"

# Install upstart service
echo "→ Installing upstart service…"
adb shell "mkdir -p /home/$PHONE_USER/.config/upstart"
adb push $UPSTART_CONF /home/$PHONE_USER/.config/upstart/callscreener-daemon.conf

# Set up call forwarding instructions
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Installation complete!            "
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo ""
echo "1. Add your WAV files to assets/audio/ and re-run this script"
echo ""
echo "2. On the phone, enable call forwarding for unanswered calls:"
echo "   Dial:  *61*+15550149823*11*5#"
echo "          (replace +15550149823 with your phone's own number)"
echo "   This forwards unanswered calls to the local SIP daemon."
echo ""
echo "3. Start the daemon manually first to test:"
echo "   adb shell 'python3 $INSTALL_DIR/callscreener_daemon.py'"
echo ""
echo "4. Or start via upstart:"
echo "   adb shell 'initctl --user start callscreener-daemon'"
echo ""
echo "5. Install the QML app via Clickable:"
echo "   clickable build --install"
echo ""
