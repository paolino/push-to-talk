#!/usr/bin/env python3
"""Push-to-talk daemon: hold a key to record, release to transcribe and type."""

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import evdev
from evdev import ecodes

log = logging.getLogger("push-to-talk")

MODEL_URLS = {
    "tiny.en": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin",
    "base.en": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin",
    "small.en": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin",
    "small": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin",
    "medium.en": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin",
    "medium": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin",
    "large": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large.bin",
}


def model_path(model_name: str) -> Path:
    """Return path to the whisper model file, downloading if needed."""
    data_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    model_dir = data_dir / "whisper"
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / f"ggml-{model_name}.bin"
    if not path.exists():
        url = MODEL_URLS.get(model_name)
        if url is None:
            log.error("Unknown model %s. Available: %s", model_name, list(MODEL_URLS))
            sys.exit(1)
        log.info("Downloading model %s from %s", model_name, url)
        notify("Push-to-Talk", f"Downloading model {model_name}...")
        subprocess.run(["curl", "-L", "-o", str(path), url], check=True)
        notify("Push-to-Talk", f"Model {model_name} ready")
    return path


def notify(title: str, body: str) -> None:
    """Send a desktop notification (best effort)."""
    try:
        subprocess.run(
            ["notify-send", "-t", "2000", title, body],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        pass


def find_keyboards() -> list[evdev.InputDevice]:
    """Find all keyboard input devices."""
    devices = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities(verbose=False)
        if ecodes.EV_KEY in caps:
            key_caps = caps[ecodes.EV_KEY]
            if ecodes.KEY_A in key_caps and ecodes.KEY_Z in key_caps:
                devices.append(dev)
                log.info("Found keyboard: %s (%s)", dev.name, dev.path)
    return devices


class Recorder:
    """Manages the push-to-talk recording lifecycle."""

    def __init__(self, model: Path, display_server: str) -> None:
        self.model = model
        self.display_server = display_server
        self.process: subprocess.Popen | None = None
        self.raw_file: str | None = None
        self.recording = False
        self._transcribe_lock = asyncio.Lock()

    def start(self) -> None:
        """Start recording raw PCM audio via parecord."""
        if self.recording:
            return
        fd, self.raw_file = tempfile.mkstemp(suffix=".raw", prefix="ptt-")
        os.close(fd)
        log.info("Recording to %s", self.raw_file)
        self.process = subprocess.Popen(
            [
                "parecord",
                "--format=s16le",
                "--rate=16000",
                "--channels=1",
                "--raw",
                self.raw_file,
            ],
        )
        self.recording = True
        notify("Push-to-Talk", "Recording...")

    async def stop_and_transcribe(self) -> None:
        """Stop recording, convert, transcribe, and type the result."""
        if not self.recording or self.process is None:
            return
        async with self._transcribe_lock:
            proc = self.process
            raw = self.raw_file
            self.process = None
            self.raw_file = None
            self.recording = False

            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            await self._transcribe_and_type(raw)

    async def _transcribe_and_type(self, raw_file: str) -> None:
        """Convert raw PCM to wav, run whisper, and type the result."""
        wav_file = raw_file.replace(".raw", ".wav")
        try:
            result = await asyncio.create_subprocess_exec(
                "sox",
                "-r", "16000", "-c", "1", "-b", "16", "-e", "signed", "-t", "raw",
                raw_file, wav_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await result.wait()
            if result.returncode != 0:
                log.error("sox conversion failed")
                notify("Push-to-Talk", "Audio conversion failed")
                return

            notify("Push-to-Talk", "Transcribing...")
            result = await asyncio.create_subprocess_exec(
                "whisper-cli",
                "-m", str(self.model),
                "-f", wav_file,
                "--no-timestamps",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()
            if result.returncode != 0:
                log.error("whisper-cli failed: %s", stderr.decode())
                notify("Push-to-Talk", "Transcription failed")
                return

            text = stdout.decode().strip()
            lines = [l for l in text.splitlines() if l.strip()]
            text = " ".join(lines)

            if not text or text == "[BLANK_AUDIO]":
                notify("Push-to-Talk", "No speech detected")
                return

            log.info("Transcribed: %s", text[:80])
            await self._type_text(text)
            notify("Push-to-Talk", f"Typed: {text[:80]}")

        finally:
            for f in (raw_file, wav_file):
                try:
                    os.unlink(f)
                except FileNotFoundError:
                    pass

    async def _type_text(self, text: str) -> None:
        """Type text into the focused window."""
        if self.display_server == "wayland":
            cmd = ["wtype", "--", text]
        elif self.display_server == "x11":
            cmd = ["xdotool", "type", "--clearmodifiers", "--", text]
        else:
            if os.environ.get("WAYLAND_DISPLAY"):
                cmd = ["wtype", "--", text]
            else:
                cmd = ["xdotool", "type", "--clearmodifiers", "--", text]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            log.error("Typing failed: %s", stderr.decode())


async def monitor_keyboard(
    device: evdev.InputDevice,
    key_code: int,
    recorder: Recorder,
) -> None:
    """Monitor a keyboard, grabbing it to swallow the PTT key.

    All non-PTT events are forwarded via a virtual UInput device so
    the rest of the system keeps working normally.
    """
    ui = evdev.UInput.from_device(device, name=f"ptt-forward-{device.name}")
    try:
        device.grab()
        log.info("Grabbed device: %s", device.name)
        async for event in device.async_read_loop():
            if event.type == ecodes.EV_KEY and event.code == key_code:
                if event.value == 1:  # key down
                    recorder.start()
                elif event.value == 0:  # key up
                    await recorder.stop_and_transcribe()
            else:
                ui.write_event(event)
                ui.syn()
    except OSError as e:
        log.warning("Lost device %s: %s", device.path, e)
    finally:
        try:
            device.ungrab()
        except OSError:
            pass
        ui.close()


async def run(args: argparse.Namespace) -> None:
    """Main async entry point."""
    model = model_path(args.model)
    log.info("Using model: %s", model)

    key_code = ecodes.ecodes.get(args.key)
    if key_code is None:
        log.error("Unknown key: %s", args.key)
        sys.exit(1)
    log.info("Push-to-talk key: %s (code %d)", args.key, key_code)

    keyboards = find_keyboards()
    if not keyboards:
        log.error("No keyboard devices found. Is user in 'input' group?")
        sys.exit(1)

    recorder = Recorder(model, args.display_server)
    notify("Push-to-Talk", f"Ready. Hold {args.key} to dictate.")

    tasks = [
        asyncio.create_task(monitor_keyboard(dev, key_code, recorder))
        for dev in keyboards
    ]
    await asyncio.gather(*tasks)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Push-to-talk dictation daemon")
    parser.add_argument(
        "--key",
        default="KEY_F12",
        help="evdev key name for push-to-talk (default: KEY_F12)",
    )
    parser.add_argument(
        "--model",
        default="base.en",
        help="Whisper model name (default: base.en)",
    )
    parser.add_argument(
        "--display-server",
        default="auto",
        choices=["auto", "wayland", "x11"],
        help="Display server for typing (default: auto-detect)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()
