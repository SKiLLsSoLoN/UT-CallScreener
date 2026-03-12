# Call Screener — Ubuntu Touch

Screens unknown callers automatically. No call forwarding setup.
No carrier config. No SIP. Just install and it works.

---

## How it works

```
Incoming GSM call
        │
        ▼
oFono fires VoiceCallManager.CallAdded (system DBus)
        │
        ▼
callscreener_daemon.py catches it instantly
        │
        ├─ Number in contacts? → leave it alone, normal dialer rings
        │
        └─ Unknown number?
                │
                ▼
           Answers silently via oFono (caller hears nothing yet)
                │
                ▼
           Plays greeting.wav into call audio
                │
                ▼
           Records caller for 10 seconds
                │
                ├─ You tap a reply → plays that WAV, restarts 10s window
                ├─ You tap ACCEPT → bridges to your earpiece
                ├─ You tap HANG UP → plays call_you_back.wav, disconnects
                │
                └─ 60s passes with no action from you?
                        → plays call_you_back.wav → hangs up automatically
```

The caller never hears ambient noise or your voice unless you tap Accept.

---

## WAV files to record (your voice)

Place in `~/.local/share/callscreener/audio/` on the device.
Format: **16-bit signed mono WAV, 16000 Hz**

Convert any audio file:
```bash
ffmpeg -i input.wav -acodec pcm_s16le -ac 1 -ar 16000 output.wav
```

| Filename              | What to say                                                        |
|-----------------------|--------------------------------------------------------------------|
| `greeting.wav`        | "Hi, I use a call screener. Please say your name and why you're calling." |
| `call_you_back.wav`   | "I'm not available right now. I'll call you back shortly."         |
| `what_calling.wav`    | "What are you calling about?"                                      |
| `who_is_this.wav`     | "Who is this please?"                                              |
| `leave_message.wav`   | "Please leave your name and number."                               |
| `not_interested.wav`  | "I'm not interested. Please remove this number."                   |
| `hold_on.wav`         | "One moment, let me get someone."                                  |

---

## Installation

### 1. Copy WAV files to device
```bash
adb push assets/audio/greeting.wav      /home/phablet/.local/share/callscreener/audio/
adb push assets/audio/call_you_back.wav /home/phablet/.local/share/callscreener/audio/
# ... repeat for each WAV
```
Or use the install script:
```bash
bash install.sh
```

### 2. Install Python deps (already on Ubuntu Touch)
```bash
adb shell sudo apt-get install -y python3-dbus python3-gi
```

### 3. Install the QML app
```bash
pip3 install clickable-ut
clickable build --install
```

### 4. Start the daemon
Test first:
```bash
adb shell python3 /home/phablet/.local/share/callscreener/callscreener_daemon.py
```

Enable auto-start on boot:
```bash
adb push daemon/callscreener-daemon.conf /home/phablet/.config/upstart/
adb shell initctl --user start callscreener-daemon
```

That's it. No dial codes. No carrier settings.

---

## Files

```
callscreener/
├── daemon/
│   ├── callscreener_daemon.py     ← oFono listener + audio engine
│   └── callscreener-daemon.conf   ← Upstart auto-start config
├── qml/
│   └── Main.qml                   ← UI (DBus remote control for daemon)
├── assets/audio/                  ← Your WAV files go here
├── install.sh
└── README.md
```

---

## DBus interface  (com.yourname.CallScreener)

| Direction  | Name | Signature | Meaning |
|------------|------|-----------|---------|
| QML→daemon | `PlayReply(key)` | `s` | Play reply WAV (what_calling / who_is_this / leave_message / not_interested / hold_on) |
| QML→daemon | `AcceptCall()` | — | Bridge call to earpiece |
| QML→daemon | `HangUp()` | — | Play callback WAV + disconnect |
| daemon→QML | `IncomingCall(number, name)` | `ss` | Unknown caller answered |
| daemon→QML | `StateChanged(state)` | `s` | idle/screening/listening/playing_reply/complete/accepted/auto_ending/ended |
| daemon→QML | `TimerTick(secs)` | `i` | Countdown update (0–10) |
| daemon→QML | `RecordingReady(path)` | `s` | Path to caller WAV file |

---

## Notes

- The daemon answers the call completely silently via `org.ofono.VoiceCall.Answer()`
  and routes audio manually through PulseAudio's telephony sink/source.
  Your phone's speaker and mic are untouched until you tap Accept.
- Contact matching normalises numbers and checks last 9 digits to
  handle country-code prefix variations (+1 vs 001 vs no prefix).
- The 60s auto-hangup timer resets every time you fire a reply WAV.
- Replace `yourname` throughout with your OpenStore username.
