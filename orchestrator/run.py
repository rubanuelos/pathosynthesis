"""CLI for node 03 (contract v0.3).

  python -m orchestrator.run                                   gallery: keys s/x/p, real voice on :8010
  python -m orchestrator.run --score  contract/examples/score_habit_build_dissolve.json --dry
  python -m orchestrator.run --dialogue contract/examples/dialogue_habit_build.json --dry

--score     play one score (keys: x = visitor left → resurface, p = panic)
--dialogue  one full session with a fake voice node on :8010 replaying the file's answers.
            --interp auto (default) uses the real `interpretation` package if importable,
            else replays the file's turns (scripted).
--dry       print OSC instead of sending it.

Keys: s start · x abort (to idle / to resurface) · p or SPACE panic · Ctrl-C panic + quit.
Exit codes: 0 ok · 1 invalid input/config · 3 panic.
"""
from __future__ import annotations

import argparse
import logging
import select
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

from . import mapping, osc_io
from .interp import make_interpreter
from .safety import Calibration
from .session import Controller, Questions, Session, SessionLog, load_fallbacks
from .timeline import Panicked, Timeline
from .validate import ContractError, load_json, load_score, validate_dialogue
from .voice import VOICE_URL, FakeVoice, VoiceClient

log = logging.getLogger("pathos.run")


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m orchestrator.run", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--score", help="play one score JSON (no questionnaire)")
    src.add_argument("--dialogue", help="run one session with a fake voice node replaying this dialogue")
    p.add_argument("--dry", action="store_true", help="print OSC instead of sending")
    p.add_argument("--interp", choices=("auto", "live", "scripted"), default="auto",
                   help="interpretation backend (default: live if importable, else scripted with --dialogue)")
    p.add_argument("--lang", default="en", help="language of the opener until the first answer (default en)")
    p.add_argument("--sensor", action="store_true", help="listen for /pathos/sensor/* on :9000 (parked this week)")
    p.add_argument("--speed", type=float, default=1.0, help="time compression for rehearsal (>= 1)")
    p.add_argument("--sc", default=f"{osc_io.SC_HOST}:{osc_io.SC_PORT}", help="SuperCollider host:port")
    p.add_argument("--voice", default=VOICE_URL, help="voice node base URL")
    p.add_argument("--fake-voice-delay", type=float, default=0.5, help="seconds per fake /ask")
    p.add_argument("--calibration", help="calibration JSON (default orchestrator/calibration.json)")
    p.add_argument("--log-dir", help="JSONL session logs (default orchestrator/logs)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


class KeyReader:
    """Single keys from the terminal in cbreak mode. Restores the terminal on stop()."""

    def __init__(self, on_key):
        self.on_key = on_key
        self._stop = threading.Event()
        self._old = None

    def start(self) -> bool:
        if not sys.stdin.isatty():
            log.warning("stdin is not a terminal: keys disabled (Ctrl-C still panics)")
            return False
        try:
            import termios
            import tty
        except ImportError:
            log.warning("no termios: keys disabled, use Ctrl-C")
            return False
        fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        threading.Thread(target=self._loop, name="keys", daemon=True).start()
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            r, _, _ = select.select([sys.stdin], [], [], 0.1)
            if r:
                ch = sys.stdin.read(1)
                if ch:
                    self.on_key(ch)

    def stop(self) -> None:
        self._stop.set()
        if self._old is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old)
            self._old = None


def _hostport(s: str) -> tuple[str, int]:
    host, _, port = s.rpartition(":")
    return host or "127.0.0.1", int(port)


def _play_score(args, out) -> int:
    try:
        score = load_score(args.score)
    except (ContractError, OSError) as e:
        print(e, file=sys.stderr)
        return 1
    plan = mapping.map_score(score)
    log.info("score '%s' on %s: %s (%.0f s)", score.get("title", ""), plan.diagram,
             "  ".join(f"{m.phase}@{m.at}({m.dur_s:.0f}s)" for m in plan.movements), plan.total_s)
    tl = Timeline(out, speed=args.speed)

    def on_key(ch: str) -> None:
        if ch in ("p", "P", " "):
            log.warning("PANIC KEY")
            tl.panic()
        elif ch in ("x", "X"):
            log.warning("x: visitor left")
            tl.leave()

    keys = KeyReader(on_key)
    keys.start()
    try:
        tl.play(plan)
        return 0
    except Panicked:
        log.warning("stopped by panic")
        return 3
    except KeyboardInterrupt:
        tl.panic()
        log.warning("Ctrl-C: panic sent")
        return 3
    finally:
        keys.stop()


def _sessions(args, out) -> int:
    scripted = None
    fake = None
    if args.dialogue:
        try:
            scripted = validate_dialogue(load_json(args.dialogue, "dialogue"))
        except (ContractError, OSError) as e:
            print(e, file=sys.stderr)
            return 1
        url = urlparse(args.voice)
        fake = FakeVoice.from_dialogue(scripted, host=url.hostname or "127.0.0.1", port=url.port or 8010,
                                       delay_s=args.fake_voice_delay / args.speed).start()
    try:
        interp = make_interpreter(args.interp, scripted)
        fallbacks = load_fallbacks()
    except Exception as e:   # noqa: BLE001
        print(f"cannot start: {e}", file=sys.stderr)
        return 1
    if interp is None:
        log.error("NO INTERPRETER: every session will use fallback probes and a fallback score")
    else:
        log.info("interpretation: %s", interp.name)

    voice = VoiceClient(args.voice)
    if not voice.health():
        log.error("voice node not answering at %s/health", args.voice)
    questions = Questions.load()
    slog = SessionLog(Path(args.log_dir)) if args.log_dir else SessionLog()
    sensor = osc_io.SensorListener() if args.sensor else osc_io.NullSensor()

    def make() -> Session:
        return Session(out, voice, interp, fallbacks=fallbacks, questions=questions, slog=slog,
                       speed=args.speed, lang=args.lang)

    ctl = Controller(make, out, voice, sensor, once=bool(args.dialogue))
    if args.sensor:
        sensor.on_panic = ctl.panic
    sensor.start()
    keys = KeyReader(ctl.handle_key)
    keys.start()

    out.send("/pathos/state", "idle")
    if args.dialogue:
        ctl.handle_key("s")
    else:
        log.info("ready: s = start · x = abort · p = panic")
    try:
        ctl.loop()
    except KeyboardInterrupt:
        ctl.panic()
        log.warning("Ctrl-C: panic sent, quitting")
        return 3
    finally:
        keys.stop()
        sensor.stop()
        if fake is not None:
            fake.close()
    return 3 if ctl.outcomes and ctl.outcomes[-1] == "panic" else 0


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if args.speed < 1.0:
        print("--speed must be >= 1", file=sys.stderr)
        return 1
    try:
        cal = Calibration.load(args.calibration)
    except (ValueError, OSError) as e:
        print(e, file=sys.stderr)
        return 1
    out = osc_io.OscOut(cal, dry=args.dry, sc=_hostport(args.sc))
    keepalive = osc_io.KeepAlive(out).start()
    log.info("OSC → %s · keepalive 4 Hz", "DRY (printing)" if args.dry else args.sc)
    try:
        return _play_score(args, out) if args.score else _sessions(args, out)
    finally:
        keepalive.stop()


if __name__ == "__main__":
    sys.exit(main())
