#!/usr/bin/env python3
"""
callscreener_daemon.py
======================
Ubuntu Touch call screening daemon.

Uses oFono's DBus API directly — NO call forwarding, NO SIP, NO carrier config.

Flow:
  - Listens for org.ofono.VoiceCallManager.CallAdded on the system bus
  - Every incoming call is caught here first
  - Checks caller number against device contacts (EDS / oFono phonebook)
  - Known contact  → leaves call ringing normally (does nothing)
  - Unknown caller → silently answers, plays greeting.wav, records 10s
  - If no user action in 60s → plays call_you_back.wav, hangs up
  - User can fire reply WAVs, accept (bridges to earpiece), or hang up
    via DBus commands from the QML app

Audio:
  - Uses PulseAudio directly (paplay / parec) for simplicity and
    reliability on Ubuntu Touch — no pjsip dependency needed
  - Caller hears WAV files played into the call's audio sink
  - We record from the call's audio source

Requires:
    python3-dbus  python3-gi  pulseaudio-utils
    (all pre-installed on Ubuntu Touch)

WAV format: 16-bit signed, mono, 16000 Hz
Convert:    ffmpeg -i input.wav -acodec pcm_s16le -ac 1 -ar 16000 output.wav
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import subprocess
import threading
import time
import os
import sys
import logging

# ── Logging ────────────────────────────────────────────────────────────────────
LOG_DIR = os.path.expanduser("~/.local/share/callscreener")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "screener.log")),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("callscreener")

# ── Paths ──────────────────────────────────────────────────────────────────────
AUDIO_DIR     = os.path.join(LOG_DIR, "audio")
RECORDING_DIR = os.path.join(LOG_DIR, "recordings")
os.makedirs(AUDIO_DIR,     exist_ok=True)
os.makedirs(RECORDING_DIR, exist_ok=True)

def wav(name):
    return os.path.join(AUDIO_DIR, name)

# WAV files — user records these in their own voice
GREETING_WAV        = wav("greeting.wav")
CALL_BACK_WAV       = wav("call_you_back.wav")

REPLY_WAVS = {
    "what_calling":   wav("what_calling.wav"),
    "who_is_this":    wav("who_is_this.wav"),
    "leave_message":  wav("leave_message.wav"),
    "not_interested": wav("not_interested.wav"),
    "hold_on":        wav("hold_on.wav"),
}

CALLER_WINDOW_SECS = 10   # seconds caller gets to speak after greeting
AUTO_HANGUP_SECS   = 60   # seconds before automatic callback + hangup

# ── DBus service ───────────────────────────────────────────────────────────────
DBUS_NAME      = "com.yourname.CallScreener"
DBUS_PATH      = "/com/yourname/CallScreener"
DBUS_INTERFACE = "com.yourname.CallScreener"


# ══════════════════════════════════════════════════════════════════════════════
#  Audio helpers — thin wrappers around paplay / parec (PulseAudio CLI tools)
#  These are always available on Ubuntu Touch and need no extra deps.
# ══════════════════════════════════════════════════════════════════════════════
class AudioPlayer:
    """Play a WAV file into the call audio sink (non-blocking)."""

    def __init__(self):
        self._proc = None

    def play(self, path, on_finish=None):
        self.stop()
        if not os.path.exists(path):
            log.warning(f"WAV not found: {path}")
            if on_finish:
                on_finish()
            return

        log.info(f"Playing: {path}")
        # paplay routes audio into the telephony sink on Ubuntu Touch
        self._proc = subprocess.Popen(
            ["paplay", "--device=sink.telephony", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if on_finish:
            def _wait():
                self._proc.wait()
                on_finish()
            t = threading.Thread(target=_wait, daemon=True)
            t.start()

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc = None

    def is_playing(self):
        return self._proc is not None and self._proc.poll() is None


class AudioRecorder:
    """Record incoming call audio (what the caller says) to a WAV file."""

    def __init__(self):
        self._proc = None
        self.path  = None

    def start(self, path):
        self.stop()
        self.path = path
        log.info(f"Recording caller to: {path}")
        # parec reads from the telephony source (what the caller says)
        self._proc = subprocess.Popen(
            [
                "parec",
                "--device=source.telephony",
                "--format=s16le",
                "--rate=16000",
                "--channels=1",
                "--file-format=wav",
                path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait()
            self._proc = None

    def is_recording(self):
        return self._proc is not None and self._proc.poll() is None


# ══════════════════════════════════════════════════════════════════════════════
#  Contact checker — uses oFono phonebook via system bus
# ══════════════════════════════════════════════════════════════════════════════
def normalise(number: str) -> str:
    """Strip spaces, dashes, parentheses for comparison."""
    return "".join(c for c in number if c.isdigit() or c == "+")


def is_known_contact(system_bus, number: str) -> bool:
    """
    Returns True if `number` is found in the device's address book.
    Uses oFono's Phonebook interface (vCard export).
    Falls back to False on any error so unknown callers are always screened.
    """
    if not number or number in ("", "unknown", "withheld"):
        return False

    norm_number = normalise(number)

    try:
        manager = dbus.Interface(
            system_bus.get_object("org.ofono", "/"),
            "org.ofono.Manager"
        )
        modems = manager.GetModems()

        for modem_path, modem_props in modems:
            interfaces = modem_props.get("Interfaces", [])
            if "org.ofono.Phonebook" not in interfaces:
                continue

            phonebook = dbus.Interface(
                system_bus.get_object("org.ofono", modem_path),
                "org.ofono.Phonebook"
            )

            # Import() returns a vCard-format string of all contacts
            vcards = phonebook.Import()

            # Simple number search across the whole vCard blob
            # A proper implementation would parse each TEL field
            for line in str(vcards).splitlines():
                if line.startswith("TEL"):
                    stored = normalise(line.split(":")[-1].strip())
                    # Match last 9 digits to handle country-code variations
                    if stored and (
                        stored == norm_number or
                        stored[-9:] == norm_number[-9:]
                    ):
                        log.info(f"Contact match: {number} → {stored}")
                        return True

        return False

    except dbus.DBusException as e:
        log.warning(f"Phonebook check failed ({e}) — treating as unknown")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  DBus service exposed to the QML app
# ══════════════════════════════════════════════════════════════════════════════
class ScreenerDBus(dbus.service.Object):
    """
    Methods (QML → daemon):
        PlayReply(key)   — play a reply WAV, then reopen caller window
        AcceptCall()     — bridge call to user's earpiece
        HangUp()         — play call_you_back.wav, then disconnect

    Signals (daemon → QML):
        IncomingCall(number, name)
        StateChanged(state)
        TimerTick(seconds_left)
        RecordingReady(path)
    """

    def __init__(self, bus, screener):
        super().__init__(bus, DBUS_PATH)
        self.screener = screener

    @dbus.service.signal(DBUS_INTERFACE, signature="ss")
    def IncomingCall(self, number, name):
        log.info(f"→ QML: IncomingCall({number}, {name})")

    @dbus.service.signal(DBUS_INTERFACE, signature="s")
    def StateChanged(self, state):
        log.info(f"→ QML: StateChanged({state})")

    @dbus.service.signal(DBUS_INTERFACE, signature="i")
    def TimerTick(self, seconds_left):
        pass

    @dbus.service.signal(DBUS_INTERFACE, signature="s")
    def RecordingReady(self, path):
        log.info(f"→ QML: RecordingReady({path})")

    @dbus.service.method(DBUS_INTERFACE, in_signature="s", out_signature="b")
    def PlayReply(self, key):
        return self.screener.play_reply(str(key))

    @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="b")
    def AcceptCall(self):
        return self.screener.accept_call()

    @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="b")
    def HangUp(self):
        return self.screener.hang_up(play_callback=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Main screener — listens to oFono, drives the whole call flow
# ══════════════════════════════════════════════════════════════════════════════
class CallScreener:
    """
    States:
        idle          — no active call
        screening     — greeting playing
        listening     — recording caller, countdown running
        playing_reply — reply WAV playing
        complete      — caller window closed, awaiting user decision
        accepted      — user accepted, call bridged to earpiece
        auto_ending   — 60s elapsed, playing callback WAV
        ended         — call disconnected
    """

    def __init__(self, system_bus, session_bus):
        self.system_bus  = system_bus
        self.session_bus = session_bus
        self.dbus        = None          # set after ScreenerDBus created

        self.state       = "idle"
        self._lock       = threading.Lock()

        # Current oFono call DBus proxy
        self._call_path  = None
        self._call_iface = None

        # Audio
        self.player   = AudioPlayer()
        self.recorder = AudioRecorder()

        # Timers
        self._caller_timer = None
        self._auto_timer   = None

        # oFono modem path (discovered at startup)
        self._modem_path = None
        self._vcm        = None          # VoiceCallManager interface

    # ── oFono setup ────────────────────────────────────────────────────────────
    def connect_ofono(self):
        """Find the modem and subscribe to CallAdded."""
        try:
            manager = dbus.Interface(
                self.system_bus.get_object("org.ofono", "/"),
                "org.ofono.Manager"
            )
            modems = manager.GetModems()
            if not modems:
                log.error("No oFono modems found!")
                return False

            # Use first modem (handles dual-SIM by using /ril_0)
            self._modem_path = str(modems[0][0])
            log.info(f"Using modem: {self._modem_path}")

            self._vcm = dbus.Interface(
                self.system_bus.get_object("org.ofono", self._modem_path),
                "org.ofono.VoiceCallManager"
            )

            # Subscribe to new calls
            self._vcm.connect_to_signal("CallAdded", self._on_call_added)
            log.info("Subscribed to VoiceCallManager.CallAdded ✓")
            return True

        except dbus.DBusException as e:
            log.error(f"oFono connect failed: {e}")
            return False

    # ── Incoming call from oFono ───────────────────────────────────────────────
    def _on_call_added(self, call_path, properties):
        """
        Fired by oFono for every new call (incoming AND outgoing).
        We only care about State == "incoming".
        """
        state = str(properties.get("State", ""))
        if state != "incoming":
            return

        number = str(properties.get("LineIdentification", "unknown"))
        name   = str(properties.get("Name", ""))
        log.info(f"Incoming call: {number} ('{name}')")

        with self._lock:
            if self.state != "idle":
                log.warning("Already handling a call — ignoring new one")
                return

            self._call_path  = str(call_path)
            self._call_iface = dbus.Interface(
                self.system_bus.get_object("org.ofono", self._call_path),
                "org.ofono.VoiceCall"
            )

            # Listen for this call being hung up remotely
            self._call_iface.connect_to_signal(
                "PropertyChanged", self._on_call_property_changed
            )

        # Check contacts
        if is_known_contact(self.system_bus, number):
            log.info(f"Known contact — letting call ring normally")
            # Don't touch it — the normal dialer handles it
            self._reset()
            return

        # Unknown — intercept
        log.info("Unknown caller — starting screening")
        display_name = name if name else "Unknown caller"
        GLib.idle_add(self.dbus.IncomingCall, number, display_name)

        # Answer silently (caller hears silence until greeting plays)
        try:
            self._call_iface.Answer()
            log.info("Call answered silently via oFono")
        except dbus.DBusException as e:
            log.error(f"Failed to answer call: {e}")
            self._reset()
            return

        self._set_state("screening")

        # Start 60-second auto-hangup clock
        self._auto_timer = threading.Timer(AUTO_HANGUP_SECS, self._auto_hangup)
        self._auto_timer.daemon = True
        self._auto_timer.start()

        # Play greeting — when it finishes, open caller window
        self.player.play(GREETING_WAV, on_finish=self._open_caller_window)

    def _on_call_property_changed(self, prop_name, prop_value):
        """Detect when the caller hangs up remotely."""
        if str(prop_name) == "State" and str(prop_value) in ("disconnected", ""):
            log.info("Caller hung up remotely")
            GLib.idle_add(self._handle_remote_hangup)

    def _handle_remote_hangup(self):
        self._cancel_timers()
        self.player.stop()
        self.recorder.stop()
        self._set_state("ended")
        GLib.timeout_add(2000, self._reset_to_idle)

    # ── State helpers ──────────────────────────────────────────────────────────
    def _set_state(self, state):
        self.state = state
        GLib.idle_add(self.dbus.StateChanged, state)

    def _cancel_timers(self):
        for attr in ("_caller_timer", "_auto_timer"):
            t = getattr(self, attr, None)
            if t:
                t.cancel()
            setattr(self, attr, None)

    def _reset(self):
        self._call_path  = None
        self._call_iface = None
        self.state       = "idle"

    def _reset_to_idle(self):
        self._reset()
        GLib.idle_add(self.dbus.StateChanged, "idle")
        return False  # don't repeat GLib timeout

    # ── Greeting → caller window ───────────────────────────────────────────────
    def _open_caller_window(self):
        """Called when greeting WAV finishes playing."""
        with self._lock:
            if self.state not in ("screening", "playing_reply"):
                return
            self._set_state("listening")

        log.info(f"Caller window open — {CALLER_WINDOW_SECS}s")

        # Start recording what the caller says
        ts = int(time.time())
        rec_path = os.path.join(RECORDING_DIR, f"caller_{ts}.wav")
        self.recorder.start(rec_path)

        # Tick countdown to UI
        self._run_countdown(CALLER_WINDOW_SECS, rec_path)

    def _run_countdown(self, secs_left, rec_path):
        GLib.idle_add(self.dbus.TimerTick, secs_left)
        if secs_left > 0:
            self._caller_timer = threading.Timer(
                1.0, lambda: self._run_countdown(secs_left - 1, rec_path)
            )
            self._caller_timer.daemon = True
            self._caller_timer.start()
        else:
            self._end_caller_window(rec_path)

    def _end_caller_window(self, rec_path):
        with self._lock:
            if self.state != "listening":
                return
            self.recorder.stop()
            self._set_state("complete")
        GLib.idle_add(self.dbus.RecordingReady, rec_path)
        log.info(f"Caller window closed — recording: {rec_path}")

    # ── Reply playback ─────────────────────────────────────────────────────────
    def play_reply(self, key: str) -> bool:
        with self._lock:
            if self.state not in ("listening", "complete", "screening"):
                log.warning(f"PlayReply called in wrong state: {self.state}")
                return False

            wav_path = REPLY_WAVS.get(key)
            if not wav_path or not os.path.exists(wav_path):
                log.warning(f"Reply WAV missing: {key} → {wav_path}")
                return False

            # Stop current countdown and recording
            self._cancel_timers()
            self.recorder.stop()
            self.player.stop()
            self._set_state("playing_reply")

        log.info(f"Playing reply: {key}")
        self.player.play(wav_path, on_finish=self._open_caller_window)

        # Reset auto-hangup clock — each reply resets the 60s timer
        if self._auto_timer:
            self._auto_timer.cancel()
        self._auto_timer = threading.Timer(AUTO_HANGUP_SECS, self._auto_hangup)
        self._auto_timer.daemon = True
        self._auto_timer.start()

        return True

    # ── Accept call ────────────────────────────────────────────────────────────
    def accept_call(self) -> bool:
        with self._lock:
            if not self._call_iface or self.state in ("idle", "accepted", "ended"):
                return False
            self._cancel_timers()
            self.player.stop()
            self.recorder.stop()
            self._set_state("accepted")

        # The call is already answered (we answered it silently).
        # Now we just stop managing the audio — PulseAudio's telephony
        # module will route it to the earpiece automatically once we
        # stop injecting our own audio into the sink.
        log.info("Call accepted — audio handed to earpiece")
        return True

    # ── Hang up ────────────────────────────────────────────────────────────────
    def hang_up(self, play_callback=False) -> bool:
        with self._lock:
            if not self._call_iface or self.state in ("idle", "ended"):
                return False
            self._cancel_timers()
            self.recorder.stop()
            self.player.stop()

        if play_callback and os.path.exists(CALL_BACK_WAV):
            self._set_state("auto_ending")
            log.info("Playing call_you_back.wav before hanging up")
            self.player.play(CALL_BACK_WAV, on_finish=self._do_hangup)
        else:
            self._do_hangup()

        return True

    def _do_hangup(self):
        try:
            if self._call_iface:
                self._call_iface.Hangup()
                log.info("Call hung up via oFono")
        except dbus.DBusException as e:
            log.warning(f"Hangup DBus error (call may already be gone): {e}")
        finally:
            self._set_state("ended")
            threading.Timer(2.0, lambda: GLib.idle_add(self._reset_to_idle)).start()

    # ── Auto-hangup after 60s ─────────────────────────────────────────────────
    def _auto_hangup(self):
        log.info("60s elapsed with no user action — auto hanging up")
        self.hang_up(play_callback=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Bootstrap
# ══════════════════════════════════════════════════════════════════════════════
def main():
    log.info("━━━ Call Screener Daemon starting ━━━")

    # DBus setup
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    system_bus  = dbus.SystemBus()
    session_bus = dbus.SessionBus()

    # Claim session bus name for QML app to talk to
    bus_name = dbus.service.BusName(DBUS_NAME, bus=session_bus)

    # Create screener
    screener    = CallScreener(system_bus, session_bus)
    dbus_svc    = ScreenerDBus(session_bus, screener)
    screener.dbus = dbus_svc

    # Connect to oFono
    if not screener.connect_ofono():
        log.error("Could not connect to oFono — retrying in 5s…")
        def retry():
            if not screener.connect_ofono():
                log.error("Retry failed. Is oFono running?")
            return False
        GLib.timeout_add(5000, retry)

    log.info(f"DBus service ready: {DBUS_NAME}")
    log.info("Listening for incoming calls…")
    log.info("Known contacts → ring normally | Unknown → screened")

    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        log.info("Shutting down…")


if __name__ == "__main__":
    main()
