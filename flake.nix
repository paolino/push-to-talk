{
  description = "Push-to-talk dictation daemon using whisper.cpp";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      package = pkgs.callPackage ./nix/package.nix { };
    in
    {
      packages.${system}.default = package;

      nixosModules.default = import ./nix/module.nix;

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          (pkgs.python3.withPackages (ps: [ ps.evdev ]))
          pkgs.whisper-cpp
          pkgs.sox
          pkgs.wtype
          pkgs.xdotool
          pkgs.libnotify
          pkgs.pulseaudio
          pkgs.curl
          pkgs.just
        ];
      };
    };
}
