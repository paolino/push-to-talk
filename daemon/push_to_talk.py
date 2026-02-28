#!/usr/bin/env python3
"""Push-to-talk daemon: hold a key to record, release to transcribe and type."""

import argparse
import asyncio
import logging
import os
import re
import signal
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

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

SKIP_MARKERS = ("[Start speaking]", "[BLANK_AUDIO]")

# How many consecutive in-progress updates must agree before typing
STABILITY_THRESHOLD = 3


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


def find_devices(key_code: int) -> list[evdev.InputDevice]:
    """Find all input devices that support the given key/button code."""
    devices = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        caps = dev.capabilities(verbose=False)
        if ecodes.EV_KEY in caps and key_code in caps[ecodes.EV_KEY]:
            devices.append(dev)
            log.info("Found device: %s (%s)", dev.name, dev.path)
    return devices


class BaseRecorder:
    """Shared functionality for batch and stream recorders."""

    def __init__(self, model: Path, display_server: str) -> None:
        self.model = model
        self.display_server = display_server

    async def _press_key(self, key: str) -> None:
        """Press a single key via wtype/xdotool."""
        if self.display_server == "wayland" or (
            self.display_server == "auto" and os.environ.get("WAYLAND_DISPLAY")
        ):
            cmd = ["wtype", "-k", key]
        else:
            cmd = ["xdotool", "key", key]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

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

    async def start(self) -> None:
        """Start recording or streaming."""
        raise NotImplementedError

    async def stop_and_transcribe(self) -> None:
        """Stop and produce transcription."""
        raise NotImplementedError


class Recorder(BaseRecorder):
    """Batch mode: record on key-down, transcribe on key-up.

    Starts parec on key-down, captures audio to memory via stdout,
    writes WAV on key-up. A short beep signals when recording is live.
    """

    def __init__(self, model: Path, display_server: str) -> None:
        super().__init__(model, display_server)
        self.process: asyncio.subprocess.Process | None = None
        self.chunks: list[bytes] = []
        self.recording = False
        self._transcribe_lock = asyncio.Lock()
        self._read_task: asyncio.Task | None = None

    async def _read_audio(self, stdout: asyncio.StreamReader) -> None:
        """Read audio chunks from parec stdout into memory."""
        while True:
            chunk = await stdout.read(4096)
            if not chunk:
                break
            self.chunks.append(chunk)

    async def start(self) -> None:
        """Start parec and collect audio chunks."""
        if self.recording:
            return
        self.chunks = []
        self.process = await asyncio.create_subprocess_exec(
            "parec",
            "--format=s16le",
            "--rate=16000",
            "--channels=1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.recording = True
        self._read_task = asyncio.create_task(self._read_audio(self.process.stdout))
        # Wait for first chunk to confirm parec is streaming
        while not self.chunks and self.recording:
            await asyncio.sleep(0.05)
        log.info("Recording started")
        notify("Push-to-Talk", "Recording...")

    async def stop_and_transcribe(self) -> None:
        """Stop parec, write WAV from buffer, transcribe."""
        if not self.recording or self.process is None:
            return
        async with self._transcribe_lock:
            proc = self.process
            self.process = None
            self.recording = False

            await asyncio.sleep(1)
            proc.kill()
            await proc.wait()
            if self._read_task:
                await self._read_task
                self._read_task = None

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
            await self._press_key("Return")
            notify("Push-to-Talk", f"Typed: {text[:80]}")

        finally:
            try:
                os.unlink(wav_file)
            except FileNotFoundError:
                pass


class StreamRecorder(BaseRecorder):
    """Stream mode: real-time transcription using whisper-stream.

    Launches whisper-stream on key-down which captures audio via SDL2
    and outputs incremental transcription. Committed text blocks are
    typed immediately; remaining in-progress text is typed on key-up.
    """

    def __init__(
        self,
        model: Path,
        display_server: str,
        step_ms: int,
        length_ms: int,
        keep_ms: int,
        capture_id: int | None,
    ) -> None:
        super().__init__(model, display_server)
        self.step_ms = step_ms
        self.length_ms = length_ms
        self.keep_ms = keep_ms
        self.capture_id = capture_id
        self.process: asyncio.subprocess.Process | None = None
        self.streaming = False
        self._parse_task: asyncio.Task | None = None
        self._in_progress: str = ""
        self._stable_typed: str = ""  # permanently typed, never backspaced
        self._prev_texts: list[str] = []  # history for stability detection
        self._transcribe_lock = asyncio.Lock()

    async def start(self) -> None:
        """Launch whisper-stream for real-time transcription."""
        if self.streaming:
            return

        cmd = [
            "whisper-stream",
            "--step", str(self.step_ms),
            "--length", str(self.length_ms),
            "--keep", str(self.keep_ms),
            "-kc",
            "-m", str(self.model),
        ]
        if self.capture_id is not None:
            cmd.extend(["--capture", str(self.capture_id)])

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.streaming = True
        self._in_progress = ""
        self._stable_typed = ""
        self._prev_texts = []
        self._parse_task = asyncio.create_task(self._parse_output())

        # Check for early death (SDL2 init failure)
        await asyncio.sleep(0.3)
        if self.process.returncode is not None:
            stderr_data = await self.process.stderr.read()
            log.error(
                "whisper-stream died on startup: %s", stderr_data.decode()
            )
            notify("Push-to-Talk", "Stream mode failed (SDL2 error?)")
            self.streaming = False
            return

        log.info("Streaming started")
        notify("Push-to-Talk", "Streaming...")

    def _update_stable(self, new_text: str) -> str | None:
        """Track stability and return new text to type, if any.

        Only text that has been consistent across STABILITY_THRESHOLD
        consecutive updates gets typed. Returns the suffix to append
        to what's already on screen, or None if nothing new is stable.
        """
        self._prev_texts.append(new_text)
        if len(self._prev_texts) > STABILITY_THRESHOLD:
            self._prev_texts.pop(0)
        self._in_progress = new_text

        if len(self._prev_texts) < STABILITY_THRESHOLD:
            return None

        # Find longest common prefix across all recent texts
        stable = self._prev_texts[0]
        for t in self._prev_texts[1:]:
            i = 0
            for a, b in zip(stable, t):
                if a != b:
                    break
                i += 1
            stable = stable[:i]

        # Only type what extends beyond already-typed stable text
        if len(stable) > len(self._stable_typed):
            suffix = stable[len(self._stable_typed):]
            self._stable_typed = stable
            return suffix
        return None

    async def _parse_output(self) -> None:
        """Read whisper-stream stdout, type stable text incrementally.

        whisper-stream uses ANSI ``\\033[2K\\r`` to overwrite the current
        line (in-progress text) and ``\\n`` to commit finalized text.

        In-progress updates are tracked for stability: only text that
        survives multiple consecutive updates is typed. This avoids
        backspacing entirely — text only ever appends. On commit or
        key-up, the remaining untyped text is flushed.
        """
        line_buf = ""
        while self.streaming and self.process and self.process.stdout:
            chunk = await self.process.stdout.read(1024)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")

            for char in text:
                if char == "\n":
                    clean = ANSI_RE.sub("", line_buf).strip()
                    line_buf = ""
                    if not clean or clean in SKIP_MARKERS:
                        continue
                    log.info("Committed: %s", clean)
                    # Type whatever hasn't been typed yet
                    remaining = clean[len(self._stable_typed):]
                    if remaining:
                        await self._type_text(remaining + " ")
                    else:
                        await self._type_text(" ")
                    self._stable_typed = ""
                    self._prev_texts = []
                    self._in_progress = ""
                elif char == "\r":
                    clean = ANSI_RE.sub("", line_buf).strip()
                    line_buf = ""
                    if clean and clean not in SKIP_MARKERS:
                        suffix = self._update_stable(clean)
                        if suffix:
                            log.debug("Stable: +%s", suffix)
                            await self._type_text(suffix)
                else:
                    line_buf += char

        # Handle remaining buffer
        if line_buf:
            clean = ANSI_RE.sub("", line_buf).strip()
            if clean and clean not in SKIP_MARKERS:
                self._update_stable(clean)

    async def stop_and_transcribe(self) -> None:
        """Stop whisper-stream, type remaining in-progress text."""
        if not self.streaming or self.process is None:
            return
        async with self._transcribe_lock:
            proc = self.process
            self.process = None
            self.streaming = False

            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

            if self._parse_task:
                await self._parse_task
                self._parse_task = None

            # Type whatever in-progress text hasn't been typed yet
            if self._in_progress:
                remaining = self._in_progress[len(self._stable_typed):]
                if remaining:
                    log.info("Flushing: %s", remaining)
                    await self._type_text(remaining)
            self._in_progress = ""
            self._stable_typed = ""
            self._prev_texts = []

            await self._press_key("Return")
            log.info("Streaming stopped")


async def monitor_device(
    device: evdev.InputDevice,
    key_codes: set[int],
    recorder: BaseRecorder,
) -> None:
    """Monitor an input device for PTT keys/buttons (passive, no grab)."""
    try:
        async for event in device.async_read_loop():
            if event.type == ecodes.EV_KEY and event.code in key_codes:
                if event.value == 1:  # key down
                    await recorder.start()
                elif event.value == 0:  # key up
                    await recorder.stop_and_transcribe()
    except OSError as e:
        log.warning("Lost device %s: %s", device.path, e)


async def run(args: argparse.Namespace) -> None:
    """Main async entry point."""
    model = model_path(args.model)
    log.info("Using model: %s", model)

    key_codes = set()
    for key_name in args.key:
        code = ecodes.ecodes.get(key_name)
        if code is None:
            log.error("Unknown key: %s", key_name)
            sys.exit(1)
        key_codes.add(code)
        log.info("Push-to-talk key: %s (code %d)", key_name, code)

    # Collect unique devices that support any of the requested keys
    seen_paths = set()
    devices = []
    for code in key_codes:
        for dev in find_devices(code):
            if dev.path not in seen_paths:
                seen_paths.add(dev.path)
                devices.append(dev)

    if not devices:
        log.error("No input devices found for %s. Is user in 'input' group?", args.key)
        sys.exit(1)

    if args.mode == "stream":
        recorder = StreamRecorder(
            model,
            args.display_server,
            args.step_ms,
            args.length_ms,
            args.keep_ms,
            args.capture_id,
        )
    else:
        recorder = Recorder(model, args.display_server)

    key_names = ", ".join(args.key)
    notify("Push-to-Talk", f"Ready ({args.mode}). Hold {key_names} to dictate.")

    tasks = [
        asyncio.create_task(monitor_device(dev, key_codes, recorder))
        for dev in devices
    ]
    await asyncio.gather(*tasks)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Push-to-talk dictation daemon")
    parser.add_argument(
        "--key",
        nargs="+",
        default=["KEY_F12"],
        help="evdev key/button names for push-to-talk, e.g. KEY_F12 BTN_SIDE (default: KEY_F12)",
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
        "--mode",
        default="batch",
        choices=["batch", "stream"],
        help="Transcription mode (default: batch)",
    )
    parser.add_argument(
        "--step-ms",
        type=int,
        default=500,
        help="Stream mode: audio step size in ms (default: 500)",
    )
    parser.add_argument(
        "--length-ms",
        type=int,
        default=5000,
        help="Stream mode: audio buffer length in ms (default: 5000)",
    )
    parser.add_argument(
        "--keep-ms",
        type=int,
        default=200,
        help="Stream mode: audio to keep from previous step in ms (default: 200)",
    )
    parser.add_argument(
        "--capture-id",
        type=int,
        default=None,
        help="Stream mode: SDL audio capture device ID",
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
