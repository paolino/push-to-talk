# Push-to-talk development recipes

# Run the daemon with verbose logging
run:
    python3 daemon/push_to_talk.py --verbose

# Run with a specific key
run-key key="KEY_F12":
    python3 daemon/push_to_talk.py --verbose --key {{ key }}

# Build the nix package
build:
    nix build

# Test the built package
test-build:
    nix build && ./result/bin/push-to-talk --help

# Enter dev shell
dev:
    nix develop

# CI checks
ci: build
