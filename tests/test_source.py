"""Tests for choosing the microphone batch mode records from."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "daemon"))
from push_to_talk import Source, choose_source

HOLLYLAND = Source(
    name="alsa_input.usb-Shenzhen_Hollyland_Technology_Co._Ltd_Wireless_Microphone-01.analog-stereo",
    description="Wireless Microphone Analog Stereo",
)
BUILTIN = Source(
    name="alsa_input.pci-0000_00_1f.3.analog-stereo",
    description="Built-in Audio Analog Stereo",
)
MONITOR = Source(
    name="alsa_output.pci-0000_00_1f.3.analog-stereo.monitor",
    description="Monitor of Built-in Audio Analog Stereo",
)
SOURCES = [HOLLYLAND, MONITOR, BUILTIN]


def test_preferred_matches_name_case_insensitively():
    choice = choose_source(SOURCES, "hollyland", BUILTIN.name)
    assert choice.source == HOLLYLAND
    assert choice.preferred_found


def test_preferred_matches_description():
    choice = choose_source(SOURCES, "built-in", HOLLYLAND.name)
    assert choice.source == BUILTIN
    assert choice.preferred_found


def test_missing_preferred_falls_back_to_default():
    choice = choose_source([MONITOR, BUILTIN], "hollyland", BUILTIN.name)
    assert choice.source == BUILTIN
    assert not choice.preferred_found


def test_monitors_never_match_preferred():
    choice = choose_source([MONITOR, HOLLYLAND], "built-in", HOLLYLAND.name)
    assert choice.source == HOLLYLAND
    assert not choice.preferred_found


def test_no_preference_uses_default():
    choice = choose_source(SOURCES, None, BUILTIN.name)
    assert choice.source == BUILTIN
    assert choice.preferred_found


def test_unknown_default_keeps_its_name():
    choice = choose_source([], None, "some.source")
    assert choice.source == Source(name="some.source", description="some.source")


def test_label_is_description():
    assert HOLLYLAND.label == "Wireless Microphone Analog Stereo"
