# Changelog

## [1.2.0](https://github.com/paolino/push-to-talk/compare/v1.1.0...v1.2.0) (2026-03-10)


### Features

* add --vad-thold and --no-fallback flags to stream mode ([d1ba271](https://github.com/paolino/push-to-talk/commit/d1ba27159c26913431cdb7cde3977bfb319d25e2))
* add --whisper-url for remote transcription ([a1cd7e5](https://github.com/paolino/push-to-talk/commit/a1cd7e5b1fe6e415a14f00281e6664b6c41ffdfe))
* add vadThreshold and noFallback options to reduce hallucinations ([2596276](https://github.com/paolino/push-to-talk/commit/25962768f41adc004b02e426a4221af61a5c3cb8))

## [1.1.0](https://github.com/paolino/push-to-talk/compare/v1.0.0...v1.1.0) (2026-02-28)


### Features

* add real-time streaming transcription with Vulkan GPU support ([3a70c81](https://github.com/paolino/push-to-talk/commit/3a70c818307a363dd3c79462fba9eff4d18fa6ad))
* support mouse buttons as push-to-talk trigger ([3144f18](https://github.com/paolino/push-to-talk/commit/3144f182b30c5357f9f4779b149b722e64cb565a))
* support multiple push-to-talk keys ([6d0305f](https://github.com/paolino/push-to-talk/commit/6d0305fd3ef5aa83347abd6d0442aa8ad2445229))


### Bug Fixes

* remove automatic Return, add trailing space for composing ([2c74b9d](https://github.com/paolino/push-to-talk/commit/2c74b9dac2f6dc2ab6df4d06d4a399de536f53ae))
* replace backspace approach with stability filter for streaming ([44bcf1e](https://github.com/paolino/push-to-talk/commit/44bcf1ea006cc43bd42b7c10e507dac6029abcd3))
* type in-progress text immediately with backspace correction ([f75eeb9](https://github.com/paolino/push-to-talk/commit/f75eeb9a4ea5f9a67a01cb19068182a0c3fdf7fa))
* use diff-based typing to reduce flickering in stream mode ([73e23aa](https://github.com/paolino/push-to-talk/commit/73e23aafca161ed7bc62810a34873a40e5ea4711))

## 1.0.0 (2026-02-28)


### Features

* append newline after typed text ([cf68de0](https://github.com/paolino/push-to-talk/commit/cf68de0836f93ef53d4fbb11764df0704be3d423))
* push-to-talk dictation daemon ([ebff131](https://github.com/paolino/push-to-talk/commit/ebff131e61f91ce289ddfd576ecc593e862f2d02))


### Bug Fixes

* capture audio in-process to prevent truncation ([1a686a6](https://github.com/paolino/push-to-talk/commit/1a686a6fe18723ee0984b51f14ccf1f1dc288bb8))
* grab evdev device to prevent PTT key leaking to terminal ([f91ddc3](https://github.com/paolino/push-to-talk/commit/f91ddc3b890513e4924f7b494829893109eba5e3))
* keep parec always running to eliminate startup latency ([4825556](https://github.com/paolino/push-to-talk/commit/482555615ab07fbce68a53cefbb87847e0d66441))
* press Return key instead of typing newline character ([95563e5](https://github.com/paolino/push-to-talk/commit/95563e51498a4d509338d4c51fb00f8926f3c0b1))
* race condition in read_audio accessing None process ([7f311ce](https://github.com/paolino/push-to-talk/commit/7f311ce1ea9b42c92f17c17942fbc0e956704058))
* reduce post-release delay to 1s ([2c0c9b8](https://github.com/paolino/push-to-talk/commit/2c0c9b8aef8557910ea858b7b4963cf3cce7027e))
* remove evdev grab that captured all keyboard input ([c440c2d](https://github.com/paolino/push-to-talk/commit/c440c2dde6e34c709aaa31d11c183d95bb532ee7))
* revert always-on mic, start parec on demand ([baeeb18](https://github.com/paolino/push-to-talk/commit/baeeb1846af22f554184cc6a2c3515afc5fe8275))
* use parecord with WAV output instead of sox rec ([b51a255](https://github.com/paolino/push-to-talk/commit/b51a255633e920a60906b245a392475150cefcc2))
* use SIGTERM + drain instead of kill to prevent end truncation ([f2e56e0](https://github.com/paolino/push-to-talk/commit/f2e56e0aa9ac3eec87bdd324183da0d177d4459c))
* use SIGTERM for sox to flush audio buffer before exit ([5084931](https://github.com/paolino/push-to-talk/commit/50849310735792576832d9be0bd0850fefb5b0e0))
* use sox rec instead of parecord ([0547666](https://github.com/paolino/push-to-talk/commit/054766600bb1e061508a398f48308eb269f5099a))
* wait 2s after key-up before stopping parec ([44eef8b](https://github.com/paolino/push-to-talk/commit/44eef8b2ca8ed0bcd9f2b303870a6bdafd48c9b9))

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
