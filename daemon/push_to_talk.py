#!/usr/bin/env python3
"""Push-to-talk daemon: hold a key to record, release to transcribe and type."""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import tempfile
import wave
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
    """Manages the push-to-talk recording lifecycle.

    Keeps parec running continuously to avoid startup latency.
    On key-down, starts collecting chunks. On key-up, stops
    collecting and transcribes the buffered audio.
    """

    def __init__(self, model: Path, display_server: str) -> None:
        self.model = model
        self.display_server = display_server
        self.process: asyncio.subprocess.Process | None = None
        self.chunks: list[bytes] = []
        self.recording = False
        self._transcribe_lock = asyncio.Lock()
        self._read_task: asyncio.Task | None = None

    async def ensure_parec(self) -> None:
        """Start parec if not already running."""
        if self.process is not None:
            return
        self.process = await asyncio.create_subprocess_exec(
            "parec",
            "--format=s16le",
            "--rate=16000",
            "--channels=1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._read_task = asyncio.create_task(self._read_audio())
        log.info("parec started (always-on)")

    async def _read_audio(self) -> None:
        """Read audio chunks from parec, keep only while recording."""
        assert self.process and self.process.stdout
        while True:
            chunk = await self.process.stdout.read(4096)
            if not chunk:
                break
            if self.recording:
                self.chunks.append(chunk)

    async def start(self) -> None:
        """Start collecting audio chunks."""
        if self.recording:
            return
        await self.ensure_parec()
        self.chunks = []
        self.recording = True
        log.info("Recording started")
        notify("Push-to-Talk", "Recording...")

    async def stop_and_transcribe(self) -> None:
        """Stop collecting, write WAV from buffer, transcribe."""
        if not self.recording:
            return
        async with self._transcribe_lock:
            self.recording = False

            pcm_data = b"".join(self.chunks)
            self.chunks = []
            log.info("Captured %d bytes of audio (%.1fs)",
                     len(pcm_data), len(pcm_data) / 32000)

            if len(pcm_data) < 3200:  # less than 0.1s
                notify("Push-to-Talk", "Too short")
                return

            fd, wav_file = tempfile.mkstemp(suffix=".wav", prefix="ptt-")
            os.close(fd)
            with wave.open(wav_file, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm_data)

            await self._transcribe_and_type(wav_file)

    async def _transcribe_and_type(self, wav_file: str) -> None:
        """Run whisper on the WAV file and type the result."""
        try:
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

            log.info("Transcribed: %s", text)
            await self._type_text(text)
            notify("Push-to-Talk", f"Typed: {text[:80]}")

        finally:
            try:
                os.unlink(wav_file)
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
    """Monitor a keyboard for the PTT key (passive, no grab)."""
    try:
        async for event in device.async_read_loop():
            if event.type == ecodes.EV_KEY and event.code == key_code:
                if event.value == 1:  # key down
                    log.info("KEY DOWN on %s", device.name)
                    await recorder.start()
                elif event.value == 0:  # key up
                    log.info("KEY UP on %s", device.name)
                    await recorder.stop_and_transcribe()
    except OSError as e:
        log.warning("Lost device %s: %s", device.path, e)


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
