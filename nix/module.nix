{ config, lib, pkgs, ... }:
let
  cfg = config.services.push-to-talk;
  package = pkgs.callPackage ./package.nix { };
in
{
  options.services.push-to-talk = {
    enable = lib.mkEnableOption "push-to-talk dictation daemon";

    user = lib.mkOption {
      type = lib.types.str;
      description = "User to run the service as and add to the input group.";
    };

    key = lib.mkOption {
      type = lib.types.str;
      default = "KEY_F12";
      description = "evdev key name for push-to-talk trigger.";
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
        ExecStart = lib.concatStringsSep " " [
          "${cfg.package}/bin/push-to-talk"
          "--key ${cfg.key}"
          "--model ${cfg.whisperModel}"
          "--display-server ${cfg.displayServer}"
        ];
        Restart = "on-failure";
        RestartSec = 5;
      };
    };
  };
}
