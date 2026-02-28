# push-to-talk

Hold a key to record, release to transcribe and type. Local speech-to-text using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — no cloud, no API keys, no data leaves your machine.

## How it works

1. Hold the push-to-talk key (default: F12)
2. Speak
3. Release the key
4. Transcribed text is typed into the focused window (no Enter — compose across multiple segments)

Audio is captured via PulseAudio/PipeWire, transcribed locally by whisper.cpp, and injected via `wtype` (Wayland) or `xdotool` (X11). Multiple keys can trigger push-to-talk simultaneously (e.g. a keyboard key and a mouse button).

## Transcription modes

### Batch mode (default)

Records audio while the key is held, then transcribes the full recording on key-up. Best accuracy, but text only appears after you stop speaking.

### Stream mode

Uses `whisper-stream` for real-time transcription — text appears as you speak. Uses SDL2 for audio capture with a sliding window approach. **Requires Vulkan GPU** — CPU is too slow for real-time inference. Vulkan is enabled by default in the Nix package.

Stream mode uses a **stability filter**: text is only typed once it has been consistent across 3 consecutive whisper-stream updates. This avoids flickering from the sliding window re-evaluating its buffer. Unstable text is flushed on commit or key-up.

```bash
# Standalone stream mode
nix develop -c python3 daemon/push_to_talk.py --key KEY_F12 --mode stream --verbose
```

Stream mode parameters:
- `--step-ms` — audio step size (default: 500ms)
- `--length-ms` — audio buffer length (default: 5000ms)
- `--keep-ms` — audio kept from previous step (default: 200ms)
- `--capture-id` — SDL audio capture device ID (default: system default)

## NixOS module

Add the flake input and enable the service:

```nix
# flake.nix
inputs.push-to-talk = {
  url = "github:paolino/push-to-talk";
  inputs.nixpkgs.follows = "nixpkgs";
};

# In your modules list:
inputs.push-to-talk.nixosModules.default
```

```nix
# Batch mode (default)
services.push-to-talk = {
  enable = true;
  user = "your-username";
  key = "KEY_F12";
  whisperModel = "base.en";
};
```

```nix
# Stream mode — real-time transcription
services.push-to-talk = {
  enable = true;
  user = "your-username";
  key = "KEY_F12";
  whisperModel = "small.en";
  mode = "stream";
  # vulkanSupport = true;  # enabled by default, requires Vulkan GPU
  # streamStepMs = 500;    # optional tuning
  # streamLengthMs = 5000;
  # streamKeepMs = 200;
  # captureDeviceId = 0;   # specific SDL capture device
};
```

The `key` option accepts a string or a list of strings for multiple triggers:

```nix
services.push-to-talk.key = [ "KEY_F13" "BTN_SIDE" ];
```

The module adds your user to the `input` group and creates a systemd user service that starts with the graphical session.

### Key leaking

The daemon reads keys passively via evdev — it does not grab the input device. The push-to-talk key will leak into the focused application. To prevent this, remap the key at the compositor or system level. For example, with [keyd](https://github.com/rvaiya/keyd):

```nix
services.keyd = {
  enable = true;
  keyboards.default = {
    ids = [ "*" ];
    settings.main.f12 = "f13";
  };
};

services.push-to-talk.key = "KEY_F13";
```

F13 is ignored by all applications, so nothing leaks.

## Standalone usage

```bash
# Batch mode
nix develop -c python3 daemon/push_to_talk.py --key KEY_F12 --verbose

# Stream mode
nix develop -c python3 daemon/push_to_talk.py --key KEY_F12 --mode stream --verbose

# Multiple keys
nix develop -c python3 daemon/push_to_talk.py --key KEY_F12 BTN_SIDE --mode stream --verbose
```

Requires your user to be in the `input` group (`sudo usermod -aG input $USER`).

## Whisper models

Models are downloaded automatically on first use to `~/.local/share/whisper/`. Available models:

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| `tiny.en` | 75 MB | Fastest | Low |
| `base.en` | 142 MB | Fast | Good |
| `small.en` | 466 MB | Medium | Better |
| `medium.en` | 1.5 GB | Slow | High |
| `large` | 2.9 GB | Slowest | Highest |

For batch mode, `base.en` offers the best speed/quality tradeoff. For stream mode with a Vulkan GPU, `small.en` works well.

## Non-NixOS installation (untested)

This project is only tested on NixOS. The instructions below are provided as guidance but may require adjustments.

### Dependencies

- Python 3.11+
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — `whisper-cli` (batch mode) and `whisper-stream` (stream mode) must be on `PATH`
- [python-evdev](https://python-evdev.readthedocs.io/) — `pip install evdev`
- `wtype` (Wayland) or `xdotool` (X11) for typing output
- `parecord` (from PulseAudio/PipeWire) for audio capture in batch mode
- Stream mode: SDL2 with audio capture support, Vulkan GPU drivers

### Setup

```bash
git clone https://github.com/paolino/push-to-talk.git
cd push-to-talk

# Install Python dependency
pip install evdev

# Add user to input group for evdev access
sudo usermod -aG input $USER
# Log out and back in for group change to take effect

# Download a whisper model
mkdir -p ~/.local/share/whisper
curl -L -o ~/.local/share/whisper/ggml-base.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin

# Run
python3 daemon/push_to_talk.py --key KEY_F12 --verbose
```

For stream mode, set the `SDL_AUDIODRIVER` environment variable if audio capture fails:

```bash
export SDL_AUDIODRIVER=pipewire,pulseaudio,alsa
python3 daemon/push_to_talk.py --key KEY_F12 --mode stream --verbose
```

## Requirements

- Linux with PulseAudio or PipeWire (with PulseAudio compatibility)
- Wayland (`wtype`) or X11 (`xdotool`) for typing output
- User in `input` group for evdev access
- Stream mode: Vulkan-capable GPU and SDL2 audio support (provided via Nix wrapper on NixOS)

## Alternatives

| Project | Streaming | NixOS module | Input method | Typing method |
|---------|-----------|--------------|--------------|---------------|
| **push-to-talk** (this) | Yes (stability filter) | Yes | evdev (multi-key) | wtype/xdotool |
| [whisper-dictation](https://github.com/jacopone/whisper-dictation) | No | Yes | evdev | ydotool |
| [turbo-whisper](https://github.com/knowall-ai/turbo-whisper) | No | No | Global hotkey | Auto-type |
| [BlahST](https://github.com/QuantiusBenignus/BlahST) | Yes (clipboard-based) | No | Hotkey | Clipboard paste |
| [voice_typing](https://github.com/themanyone/voice_typing) | No | No | sox silence detection | xdotool |
| [Voxtype](https://voxtype.io/) | No | No | Compositor binding | Clipboard |
| [TalkType](https://github.com/lmacan1/talktype) | No | No | Hotkey toggle | Terminal only |

Key differences in this project: real-time streaming via `whisper-stream` with a stability filter to avoid flickering, Vulkan GPU acceleration out of the box, multiple simultaneous trigger keys, and composable dictation (no automatic Enter — build up text across segments).

## License

MIT
