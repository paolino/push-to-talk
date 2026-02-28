# push-to-talk

Hold a key to record, release to transcribe and type. Local speech-to-text using [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — no cloud, no API keys, no data leaves your machine.

## How it works

1. Hold the push-to-talk key (default: F12)
2. Speak
3. Release the key
4. Transcribed text is typed into the focused window

Audio is captured via PulseAudio/PipeWire, transcribed locally by whisper.cpp, and injected via `wtype` (Wayland) or `xdotool` (X11).

## Transcription modes

### Batch mode (default)

Records audio while the key is held, then transcribes the full recording on key-up. Best accuracy, but text only appears after you stop speaking.

### Stream mode

Uses `whisper-stream` for real-time transcription — text appears as you speak. Uses SDL2 for audio capture with a sliding window approach. Lower latency but may produce intermediate corrections.

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
  displayServer = "auto";
};
```

```nix
# Stream mode — real-time transcription
services.push-to-talk = {
  enable = true;
  user = "your-username";
  key = "KEY_F12";
  whisperModel = "base.en";
  mode = "stream";
  # streamStepMs = 500;    # optional tuning
  # streamLengthMs = 5000;
  # streamKeepMs = 200;
  # captureDeviceId = 0;   # specific SDL capture device
};
```

The module adds your user to the `input` group and creates a systemd user service that starts with the graphical session.

### Key leaking

The daemon reads keys passively via evdev — it does not grab the keyboard. The push-to-talk key will leak into the focused application. To prevent this, remap the key at the compositor or system level. For example, with [keyd](https://github.com/rvaiya/keyd):

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

For real-time dictation, `base.en` offers the best speed/quality tradeoff.

## Requirements

- Linux with PulseAudio or PipeWire (with PulseAudio compatibility)
- Wayland (`wtype`) or X11 (`xdotool`) for typing output
- User in `input` group for evdev access
- Stream mode: SDL2 audio support (provided via Nix wrapper)

## License

MIT
