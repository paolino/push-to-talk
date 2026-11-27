"""Tests for per-key language selection."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from evdev import ecodes

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))
from push_to_talk import Recorder, monitor_device, parse_key_languages


class TestParseKeyLanguages:
    def test_empty(self):
        assert parse_key_languages([]) == {}

    def test_pairs(self):
        assert parse_key_languages(["KEY_F14=it", "KEY_F15=pt"]) == {
            "KEY_F14": "it",
            "KEY_F15": "pt",
        }

    @pytest.mark.parametrize("spec", ["KEY_F14", "=it", "KEY_F14="])
    def test_malformed_rejected(self, spec):
        with pytest.raises(ValueError):
            parse_key_languages([spec])


class FakeDevice:
    """Yields the given (code, value) key events, then stops."""

    path = "/dev/input/fake"

    def __init__(self, events):
        self._events = events

    async def async_read_loop(self):
        for code, value in self._events:
            yield SimpleNamespace(type=ecodes.EV_KEY, code=code, value=value)


class TestMonitorDevice:
    @pytest.mark.asyncio
    async def test_language_follows_key(self):
        rec = AsyncMock()
        dev = FakeDevice([
            (ecodes.KEY_F13, 1), (ecodes.KEY_F13, 0),
            (ecodes.KEY_F14, 1), (ecodes.KEY_F14, 0),
        ])
        await monitor_device(
            dev,
            {ecodes.KEY_F13, ecodes.KEY_F14},
            rec,
            {ecodes.KEY_F14: "it"},
        )
        assert [c.args for c in rec.start.await_args_list] == [(None,), ("it",)]
        assert rec.stop_and_transcribe.await_count == 2


class TestRecorderLanguage:
    @pytest.mark.asyncio
    async def test_transcription_uses_language_of_its_own_press(self):
        """A press during transcription must not relabel the clip in flight."""
        rec = Recorder(Path("/fake/model.bin"), "wayland", language="en")
        rec.tail_ms = 0
        rec._paste_text = AsyncMock()
        seen = []

        async def fake_transcribe(wav_file, language):
            # Next press (default language) arrives while this one is
            # still transcribing.
            rec.active_language = rec.language
            seen.append(language)
            return "ciao"

        rec._transcribe_local = fake_transcribe

        proc = AsyncMock()
        proc.kill = lambda: None
        rec.process = proc
        rec.recording = True
        rec.chunks = [b"\0" * 32000]
        rec.active_language = "it"

        await rec.stop_and_transcribe()

        assert seen == ["it"]
