"""Tests for StreamRecorder ANSI parsing and lifecycle."""

import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import from daemon
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))
from push_to_talk import ANSI_RE, BaseRecorder, StreamRecorder


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


# -- Parse output tests -------------------------------------------------------


class TestParseOutput:
    """Test _parse_output with simulated whisper-stream byte streams."""

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
        return rec

    @pytest.mark.asyncio
    async def test_committed_line_typed(self):
        rec = self._make_recorder()
        data = make_stream_output(("hello world", True))
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        rec._type_text.assert_called_once_with("hello world ")
        assert rec._in_progress == ""

    @pytest.mark.asyncio
    async def test_in_progress_not_typed(self):
        rec = self._make_recorder()
        data = make_stream_output(("partial", False))
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        rec._type_text.assert_not_called()
        assert rec._in_progress == "partial"

    @pytest.mark.asyncio
    async def test_progressive_updates_then_commit(self):
        rec = self._make_recorder()
        data = make_stream_output(
            ("hel", False),
            ("hello", False),
            ("hello world", True),
        )
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        rec._type_text.assert_called_once_with("hello world ")
        assert rec._in_progress == ""

    @pytest.mark.asyncio
    async def test_multiple_committed_lines(self):
        rec = self._make_recorder()
        data = make_stream_output(
            ("first sentence", True),
            ("second sentence", True),
        )
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        assert rec._type_text.call_count == 2
        calls = [c.args[0] for c in rec._type_text.call_args_list]
        assert calls == ["first sentence ", "second sentence "]

    @pytest.mark.asyncio
    async def test_start_speaking_skipped(self):
        rec = self._make_recorder()
        data = make_stream_output(
            ("[Start speaking]", True),
            ("actual text", True),
        )
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        rec._type_text.assert_called_once_with("actual text ")

    @pytest.mark.asyncio
    async def test_start_speaking_in_progress_skipped(self):
        rec = self._make_recorder()
        data = make_stream_output(("[Start speaking]", False))
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        assert rec._in_progress == ""

    @pytest.mark.asyncio
    async def test_committed_then_in_progress_remainder(self):
        rec = self._make_recorder()
        data = make_stream_output(
            ("done sentence", True),
            ("partial next", False),
        )
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        rec._type_text.assert_called_once_with("done sentence ")
        assert rec._in_progress == "partial next"

    @pytest.mark.asyncio
    async def test_blank_audio_committed_skipped(self):
        rec = self._make_recorder()
        data = make_stream_output(
            ("[BLANK_AUDIO]", True),
            ("actual text", True),
        )
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        rec._type_text.assert_called_once_with("actual text ")

    @pytest.mark.asyncio
    async def test_blank_audio_in_progress_skipped(self):
        rec = self._make_recorder()
        data = make_stream_output(("[BLANK_AUDIO]", False))
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        assert rec._in_progress == ""

    @pytest.mark.asyncio
    async def test_empty_lines_ignored(self):
        rec = self._make_recorder()
        # Committed empty line should be skipped
        data = b"\x1b[2K\r\n\x1b[2K\rreal text\n"
        rec.process = MagicMock()
        rec.process.stdout = FakeStreamReader(data)
        rec.streaming = True

        await rec._parse_output()

        rec._type_text.assert_called_once_with("real text ")


# -- StreamRecorder lifecycle -------------------------------------------------


class TestStreamRecorderLifecycle:
    """Test start/stop with mocked subprocess."""

    @pytest.mark.asyncio
    async def test_stop_types_remaining_and_presses_return(self):
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

        # Simulate a running process
        proc = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        proc.returncode = 0
        rec.process = proc
        rec.streaming = True
        rec._in_progress = "leftover text"
        rec._parse_task = asyncio.create_task(asyncio.sleep(0))

        await rec.stop_and_transcribe()

        rec._type_text.assert_called_once_with("leftover text")
        rec._press_key.assert_called_once_with("Return")
        proc.send_signal.assert_called_once_with(signal.SIGTERM)
        assert not rec.streaming

    @pytest.mark.asyncio
    async def test_stop_no_remaining_still_presses_return(self):
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
        rec._parse_task = asyncio.create_task(asyncio.sleep(0))

        await rec.stop_and_transcribe()

        rec._type_text.assert_not_called()
        rec._press_key.assert_called_once_with("Return")

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
