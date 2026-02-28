#!/usr/bin/env python3
"""Smoke test: speak into mic, see parsed streaming output on terminal.

Usage: nix develop -c python3 tests/smoke_stream.py [--model base.en]

Press Ctrl+C to stop. Shows committed text (green) and in-progress (yellow).
"""

import asyncio
import re
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))
from push_to_talk import ANSI_RE, model_path

GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


async def run(model_name: str) -> None:
    model = model_path(model_name)
    print(f"{DIM}Model: {model}{RESET}")
    print(f"{DIM}Speak into your microphone. Ctrl+C to stop.{RESET}")
    print()

    proc = await asyncio.create_subprocess_exec(
        "whisper-stream",
        "--step", "500",
        "--length", "5000",
        "--keep", "200",
        "-kc",
        "-m", str(model),
        stdout=asyncio.subprocess.PIPE,
        stderr=None,  # pass stderr through to terminal
    )

    await asyncio.sleep(0.3)
    if proc.returncode is not None:
        print("whisper-stream died on startup (see stderr above)", file=sys.stderr)
        return

    line_buf = ""
    in_progress = ""

    try:
        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")

            for char in text:
                if char == "\n":
                    clean = ANSI_RE.sub("", line_buf).strip()
                    line_buf = ""
                    if not clean or clean in ("[Start speaking]", "[BLANK_AUDIO]"):
                        continue
                    # Clear in-progress line, print committed
                    sys.stdout.write(
                        f"\r\033[2K{GREEN}[typed] {clean}{RESET}\n"
                    )
                    sys.stdout.flush()
                    in_progress = ""
                elif char == "\r":
                    clean = ANSI_RE.sub("", line_buf).strip()
                    line_buf = ""
                    if clean and clean not in ("[Start speaking]", "[BLANK_AUDIO]"):
                        in_progress = clean
                        sys.stdout.write(
                            f"\r\033[2K{YELLOW}[hearing] {in_progress}{RESET}"
                        )
                    sys.stdout.flush()
                else:
                    line_buf += char
    except asyncio.CancelledError:
        pass
    finally:
        if in_progress:
            sys.stdout.write(
                f"\r\033[2K{GREEN}[final] {in_progress}{RESET}\n"
            )
        proc.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


def main() -> None:
    model_name = "base.en"
    if "--model" in sys.argv:
        idx = sys.argv.index("--model")
        model_name = sys.argv[idx + 1]

    try:
        asyncio.run(run(model_name))
    except KeyboardInterrupt:
        print(f"\n{DIM}Done.{RESET}")


if __name__ == "__main__":
    main()
