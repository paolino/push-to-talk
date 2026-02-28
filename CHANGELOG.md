# Changelog

## [0.1.0](https://github.com/paolino/push-to-talk/commits/v0.1.0) (2026-02-28)

### Features

* Push-to-talk dictation daemon with whisper.cpp
* NixOS module with systemd user service
* Auto-download whisper models on first use
* Wayland (wtype) and X11 (xdotool) support
* Desktop notifications for recording state
* In-process audio capture via parec for zero-loss recording
* Appends newline after typed text

### Bug Fixes

* Remove evdev grab that captured all keyboard input
* Use in-process audio buffering to prevent truncation
* Fix race condition in async audio reader
* Post-release 1s delay to capture trailing speech
