"""voice/check.py — install-time checks, no HTTP, no other node.

    python -m voice.check devices              list audio devices (pick output/input names)
    python -m voice.check tone [--hz 440]      sine on the configured voice channel ONLY (R)
    python -m voice.check speak "text" [--lang es] [--voice af_heart,af_nicole] [--speed 0.8]
                               [--pause 0.6] [--warmth -3]   (try settings without editing config)
    python -m voice.check meter [--seconds 20] live mic level + VAD flag, to set speech_gate_dbfs
    python -m voice.check turn [--lang en]     listen once, transcribe, print the /ask JSON
    python -m voice.check bakeoff [--play]     same questions through several TTS engines
                                               (see voice/bakeoff.py; --list shows what's available)

All of them read voice/config.toml (or --config).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time

from . import config as config_mod


def cmd_devices(_cfg, _args):
    import sounddevice as sd
    print(sd.query_devices())
    print(f"\nPortAudio default in/out: {sd.default.device}")


def cmd_tone(cfg, args):
    import numpy as np
    from . import audio
    audio.check_output_routing(cfg.output)
    sr = audio.device_rate(cfg.output.device, "output", cfg.output.samplerate)
    t = np.arange(int(sr * args.seconds)) / sr
    env = np.minimum(1.0, np.minimum(t / 0.05, (t[-1] - t) / 0.05))
    x = (np.sin(2 * np.pi * args.hz * t) * env * audio.db_to_amp(-18)).astype(np.float32)
    x, sr = audio.prepare(x, sr, cfg.output, normalize=False)
    print(f"{args.hz} Hz for {args.seconds}s on channel {cfg.output.channel} only "
          "(L/chair should stay silent)")
    audio.play_mono(x, sr, cfg.output, threading.Event())


def cmd_speak(cfg, args):
    from . import audio, tts
    audio.check_output_routing(cfg.output)
    t = cfg.tts
    if args.voice:
        t.kokoro_voices = {**t.kokoro_voices, args.lang: args.voice}
    if args.speed is not None:
        t.kokoro_speed = {**t.kokoro_speed, args.lang: args.speed}
    if args.pause is not None:
        t.kokoro_pause_s = args.pause
    if args.warmth is not None:
        t.warmth_db = args.warmth
    engine = tts.make(t, cfg.output)
    t0 = time.monotonic()
    x, sr = engine.synth(args.text, args.lang)
    print(f"rendered in {time.monotonic() - t0:.2f}s, {len(x) / sr:.1f}s of audio")
    audio.play_mono(x, sr, cfg.output, threading.Event())


def cmd_meter(cfg, args):
    from .listen import FRAME_S, FrameClassifier, open_input, to_frame16k
    clf = FrameClassifier(cfg.listen)
    stream, q, sr, _ = open_input(cfg)
    print(f"gate = {cfg.listen.speech_gate_dbfs} dBFS. Talk from the visitor's position, "
          "then stay quiet; set the gate between the two. Ctrl-C to stop.")
    n_print = max(1, round(0.1 / FRAME_S))
    levels, flags = [], []
    end = time.monotonic() + args.seconds
    with stream:
        while time.monotonic() < end:
            blk = q.get()
            f = to_frame16k(blk, sr)
            levels.append(clf.dbfs(f))
            flags.append(clf(f))
            if len(levels) == n_print:
                lvl = max(levels)
                bar = "#" * max(0, int((lvl + 80) / 2))
                print(f"{lvl:7.1f} dBFS {'SPEECH' if any(flags) else '      '} {bar}")
                levels, flags = [], []


def cmd_turn(cfg, args):
    from . import listen, stt
    tr = stt.Transcriber(cfg.stt)
    print("listening… (speak, then stay quiet)")
    turn = listen.capture_turn(cfg, args.end_silence, args.listen_max, threading.Event())
    answer, lang = "", args.lang
    if turn.audio is not None:
        t0 = time.monotonic()
        answer, lang = tr.transcribe(turn.audio, hint=args.lang)
        print(f"stt {time.monotonic() - t0:.2f}s")
    status = turn.status if answer else "silence"
    print(json.dumps({"answer": answer, "status": status,
                      "speech_s": round(turn.speech_s if answer else 0.0, 2), "lang": lang},
                     ensure_ascii=False))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    p = sub.add_parser("tone")
    p.add_argument("--hz", type=float, default=440.0)
    p.add_argument("--seconds", type=float, default=2.0)
    p = sub.add_parser("speak")
    p.add_argument("text")
    p.add_argument("--lang", default="en")
    p.add_argument("--voice", help="kokoro voice for --lang, e.g. af_heart or af_heart,af_nicole")
    p.add_argument("--speed", type=float, help="kokoro speed for --lang (1.0 = model default)")
    p.add_argument("--pause", type=float, help="kokoro silence between sentences, seconds")
    p.add_argument("--warmth", type=float, help="high-shelf dB above ~4.5 kHz (all engines)")
    p = sub.add_parser("meter")
    p.add_argument("--seconds", type=float, default=30.0)
    p = sub.add_parser("turn")
    p.add_argument("--lang", default="en")
    p.add_argument("--end-silence", type=float, default=2.5)
    p.add_argument("--listen-max", type=float, default=45.0)
    from . import bakeoff
    bakeoff.add_arguments(sub.add_parser("bakeoff", help="compare TTS engines"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = config_mod.load(args.config)
    {"devices": cmd_devices, "tone": cmd_tone, "speak": cmd_speak,
     "meter": cmd_meter, "turn": cmd_turn}.get(args.cmd, lambda *_: None)(cfg, args)
    if args.cmd == "bakeoff":
        return bakeoff.run(cfg, args)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
