"""Tests for StreamRecorder ANSI parsing and lifecycle."""

import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))
from push_to_talk import ANSI_RE, STABILITY_THRESHOLD, StreamRecorder


# -- ANSI stripping ----------------------------------------------------------


class TestAnsiStripping:
    def test_plain_text_unchanged(self):
        assert ANSI_RE.sub("", "hello world") == "hello world"

    def test_erase_line(self):
        assert ANSI_RE.sub("", "\x1b[2Khello") == "hello"

    def test_cursor_move(self):
        assert ANSI_RE.sub("", "\x1b[1;1Htext") == "text"

    def test_multiple_escapes(self):
        assert ANSI_RE.sub("", "\x1b[2K\x1b[0mhello\x1b[1m") == "hello"

    def test_empty_after_strip(self):
        assert ANSI_RE.sub("", "\x1b[2K").strip() == ""


# -- Simulated whisper-stream output -----------------------------------------


def make_stream_output(*updates):
    """Build raw bytes simulating whisper-stream stdout.

    Each update is (text, committed) where committed=True means the line
    ends with newline (finalized), otherwise it's overwritten in-place.
    """
    parts = []
    for text, committed in updates:
        parts.append(f"\x1b[2K\r{text}")
        if committed:
            parts.append("\n")
    return "".join(parts).encode()


class FakeStreamReader:
    """Simulate asyncio.StreamReader from a bytes buffer."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    async def read(self, n: int) -> bytes:
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + n]
        self._pos += n
        return chunk


# -- Stability filter tests ---------------------------------------------------


class TestStabilityFilter:
    """Test _update_stable: only type text stable across N updates."""

    def _make_recorder(self):
        return StreamRecorder(
            model=Path("/fake/model.bin"),
            display_server="wayland",
            step_ms=500,
            length_ms=5000,
            keep_ms=200,
            capture_id=None,
        )

    def test_no_output_before_threshold(self):
        rec = self._make_recorder()
        for _ in range(STABILITY_THRESHOLD - 1):
            assert rec._update_stable("hello world") is None

    def test_stable_text_returned_at_threshold(self):
        rec = self._make_recorder()
        for _ in range(STABILITY_THRESHOLD - 1):
            rec._update_stable("hello world")
        suffix = rec._update_stable("hello world")
        assert suffix == "hello world"
        assert rec._stable_typed == "hello world"

    def test_growing_prefix_returns_increment(self):
        rec = self._make_recorder()
        for _ in range(STABILITY_THRESHOLD):
            rec._update_stable("hello")
        assert rec._stable_typed == "hello"

        for _ in range(STABILITY_THRESHOLD - 1):
            rec._update_stable("hello world")
        suffix = rec._update_stable("hello world")
        assert suffix == " world"
        assert rec._stable_typed == "hello world"

    def test_diverging_text_types_only_common(self):
        rec = self._make_recorder()
        # Alternating — only the common prefix "hello w" can stabilize
        texts = ["hello world", "hello ward"] * STABILITY_THRESHOLD
        results = [rec._update_stable(t) for t in texts]
        typed = [r for r in results if r is not None]
        total = "".join(typed)
        assert "hello world" not in total

    def test_stable_typed_never_shrinks(self):
        rec = self._make_recorder()
        for _ in range(STABILITY_THRESHOLD):
            rec._update_stable("hello world")
        assert rec._stable_typed == "hello world"
        rec._update_stable("hello ward")
        assert rec._stable_typed == "hello world"


# -- Parse output tests -------------------------------------------------------


class TestParseOutput:
    """Test _parse_output: stability-based typing, no backspacing."""

    def _make_recorder(self):
        rec = StreamRecorder(
            model=Path("/fake/model.bin"),
            display_server="wayland",
            step_ms=500,
            length_ms=5000,
            keep_ms=200,
            capture_id=None,
        )
        rec._type_text = AsyncMock()
        rec._press_key = AsyncMock()
        return rec

    @pytest.mark.asyncio
    async def test_committed_types_full_text(self):
        rec = self._make_recorder()
        data = make_stream_output(("hello world", True))
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        type_calls = [c.args[0] for c in rec._type_text.call_args_list]
        assert "hello world " in type_calls
        assert rec._stable_typed == ""

    @pytest.mark.asyncio
    async def test_stable_then_commit_types_remainder(self):
        rec = self._make_recorder()
        updates = [("hello world", False)] * STABILITY_THRESHOLD
        updates.append(("hello world, how are you", True))
        data = make_stream_output(*updates)
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        type_calls = [c.args[0] for c in rec._type_text.call_args_list]
        assert "hello world" in type_calls
        assert ", how are you " in type_calls

    @pytest.mark.asyncio
    async def test_never_backspaces(self):
        rec = self._make_recorder()
        updates = [
            ("hel", False),
            ("hello", False),
            ("hello wor", False),
            ("hello world", False),
            ("hello ward", False),
            ("hello world", True),
        ]
        data = make_stream_output(*updates)
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        bs_calls = [
            c for c in rec._press_key.call_args_list
            if c.args[0] == "BackSpace"
        ]
        assert len(bs_calls) == 0

    @pytest.mark.asyncio
    async def test_skip_markers_filtered(self):
        rec = self._make_recorder()
        data = make_stream_output(
            ("[Start speaking]", True),
            ("[BLANK_AUDIO]", False),
            ("[BLANK_AUDIO]", False),
            ("[BLANK_AUDIO]", True),
            ("actual text", True),
        )
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        type_calls = [c.args[0] for c in rec._type_text.call_args_list]
        assert all("[" not in c for c in type_calls)
        assert "actual text " in type_calls

    @pytest.mark.asyncio
    async def test_empty_committed_ignored(self):
        rec = self._make_recorder()
        data = b"\x1b[2K\r\n\x1b[2K\rreal text\n"
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        type_calls = [c.args[0] for c in rec._type_text.call_args_list]
        assert "real text " in type_calls


# -- StreamRecorder lifecycle -------------------------------------------------


class TestStreamRecorderLifecycle:

    @pytest.mark.asyncio
    async def test_stop_flushes_untyped_remainder(self):
        rec = StreamRecorder(
            model=Path("/fake/model.bin"),
            display_server="wayland",
            step_ms=500,
            length_ms=5000,
            keep_ms=200,
            capture_id=None,
        )
        rec._type_text = AsyncMock()
        rec._press_key = AsyncMock()

        proc = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        rec.process = proc
        rec.streaming = True
        rec._in_progress = "hello world"
        rec._stable_typed = "hello"
        rec._parse_task = asyncio.create_task(asyncio.sleep(0))

        await rec.stop_and_transcribe()

        type_calls = [c.args[0] for c in rec._type_text.call_args_list]
        assert " world" in type_calls
        assert " " in type_calls
        rec._press_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_nothing_to_flush(self):
        rec = StreamRecorder(
            model=Path("/fake/model.bin"),
            display_server="wayland",
            step_ms=500,
            length_ms=5000,
            keep_ms=200,
            capture_id=None,
        )
        rec._type_text = AsyncMock()
        rec._press_key = AsyncMock()

        proc = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        rec.process = proc
        rec.streaming = True
        rec._in_progress = ""
        rec._stable_typed = ""
        rec._parse_task = asyncio.create_task(asyncio.sleep(0))

        await rec.stop_and_transcribe()

        rec._type_text.assert_called_once_with(" ")
        rec._press_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_when_not_streaming_is_noop(self):
        rec = StreamRecorder(
            model=Path("/fake/model.bin"),
            display_server="wayland",
            step_ms=500,
            length_ms=5000,
            keep_ms=200,
            capture_id=None,
        )
        rec._type_text = AsyncMock()
        rec._press_key = AsyncMock()

        await rec.stop_and_transcribe()

        rec._type_text.assert_not_called()
        rec._press_key.assert_not_called()
