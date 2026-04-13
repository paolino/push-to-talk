{
  lib,
  python3,
  makeWrapper,
  whisper-cpp,
  sox,
  wtype,
  xdotool,
  ydotool,
  libnotify,
  pulseaudio,
  curl,
}:
let
  pythonEnv = python3.withPackages (ps: [ ps.evdev ]);
in
python3.pkgs.buildPythonApplication {
  pname = "push-to-talk";
  version = "0.1.0";
  format = "other";

  src = ../daemon;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    mkdir -p $out/bin
    cp push_to_talk.py $out/bin/push-to-talk
    chmod +x $out/bin/push-to-talk
  '';

  postFixup = ''
    wrapProgram $out/bin/push-to-talk \
      --set PYTHONPATH "${pythonEnv}/${pythonEnv.sitePackages}" \
      --set SDL_AUDIODRIVER "pipewire,pulseaudio,alsa" \
      --prefix PATH : ${lib.makeBinPath [
        pythonEnv
        whisper-cpp
        sox
        wtype
        xdotool
        ydotool
        libnotify
        pulseaudio
        curl
      ]}
  '';

  meta = {
    description = "Push-to-talk dictation daemon using whisper.cpp";
    license = lib.licenses.mit;
    mainProgram = "push-to-talk";
  };
}
