{ config, lib, pkgs, ... }:
let
  cfg = config.services.push-to-talk;
  whisper-cpp' = pkgs.whisper-cpp.override {
    vulkanSupport = cfg.vulkanSupport;
  };
  package = pkgs.callPackage ./package.nix { whisper-cpp = whisper-cpp'; };
in
{
  options.services.push-to-talk = {
    enable = lib.mkEnableOption "push-to-talk dictation daemon";

    user = lib.mkOption {
      type = lib.types.str;
      description = "User to run the service as and add to the input group.";
    };

    key = lib.mkOption {
      type = with lib.types; either str (listOf str);
      default = [ "KEY_F12" ];
      description = "evdev key/button name(s) for push-to-talk trigger (e.g. KEY_F12, BTN_SIDE).";
      apply = v: if builtins.isList v then v else [ v ];
    };

    whisperModel = lib.mkOption {
      type = lib.types.str;
      default = "base.en";
      description = "Whisper model name (e.g. base.en, small, medium).";
    };

    displayServer = lib.mkOption {
      type = lib.types.enum [ "auto" "wayland" "x11" ];
      default = "auto";
      description = "Display server for typing output.";
    };

    mode = lib.mkOption {
      type = lib.types.enum [ "batch" "stream" ];
      default = "batch";
      description = "Transcription mode. Batch records then transcribes; stream types in real-time.";
    };

    streamStepMs = lib.mkOption {
      type = lib.types.int;
      default = 500;
      description = "Stream mode: audio step size in milliseconds.";
    };

    streamLengthMs = lib.mkOption {
      type = lib.types.int;
      default = 5000;
      description = "Stream mode: audio buffer length in milliseconds.";
    };

    streamKeepMs = lib.mkOption {
      type = lib.types.int;
      default = 200;
      description = "Stream mode: audio to keep from previous step in milliseconds.";
    };

    vulkanSupport = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable Vulkan GPU acceleration for whisper.cpp.";
    };

    captureDeviceId = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = "Stream mode: SDL audio capture device ID.";
    };

    vadThreshold = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = "Stream mode: voice activity detection threshold (default 0.60). Raise to reduce hallucinations on silence.";
    };

    noFallback = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Stream mode: do not use temperature fallback while decoding. Reduces hallucinations.";
    };

    package = lib.mkOption {
      type = lib.types.package;
      default = package;
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The push-to-talk package to use.";
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.${cfg.user}.extraGroups = [ "input" ];

    systemd.user.services.push-to-talk = {
      description = "Push-to-talk dictation daemon";
      wantedBy = [ "graphical-session.target" ];
      after = [ "graphical-session.target" "pulseaudio.service" "pipewire.service" ];

      serviceConfig = {
        ExecStart = lib.concatStringsSep " " (
          [
            "${cfg.package}/bin/push-to-talk"
            "--key ${lib.concatStringsSep " " cfg.key}"
            "--model ${cfg.whisperModel}"
            "--display-server ${cfg.displayServer}"
            "--mode ${cfg.mode}"
          ]
          ++ lib.optionals (cfg.mode == "stream") [
            "--step-ms ${toString cfg.streamStepMs}"
            "--length-ms ${toString cfg.streamLengthMs}"
            "--keep-ms ${toString cfg.streamKeepMs}"
          ]
          ++ lib.optionals (cfg.captureDeviceId != null) [
            "--capture-id ${toString cfg.captureDeviceId}"
          ]
          ++ lib.optionals (cfg.vadThreshold != null) [
            "--vad-thold ${toString cfg.vadThreshold}"
          ]
          ++ lib.optionals cfg.noFallback [
            "--no-fallback"
          ]
        );
        Restart = "on-failure";
        RestartSec = 5;
      };
    };
  };
}
