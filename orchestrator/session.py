"""Session loop (contract v0.3 §2.2): idle → asking → composing → playing → resurfaced → idle.

Session     one visitor, run in its own thread. All bounds, timeouts and fallbacks are enforced here:
            2–5 questions including the opener, next_turn ≤ 6 s, compose ≤ 10 s, invalid turn or score
            → fallback probe / fallback score. The piece never stalls.
Controller  operator keys (`s` start, `x` abort, `p` panic) and, with --sensor, `present`
            (held 2 s while idle → start; absent 15 s → visitor left). Owns one Session at a time.
SessionLog  JSONL, one line per event: dialogue, turns, score, timings. Transcripts only, no audio,
            no names asked or stored; session ids are random.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import queue
import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import mapping, safety
from .interp import Aborted, call_with_timeout
from .timeline import Panicked, Timeline
from .validate import ContractError, validate_score, validate_turn

log = logging.getLogger("pathos.session")

REPO = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = REPO / "interpretation" / "questions.json"
FALLBACK_DIR = Path(__file__).with_name("fallbacks")
LOG_DIR = Path(__file__).with_name("logs")

DEFAULT_OPENER = "What are you feeling right now that you don't have a right word for?"
# Used only if interpretation/questions.json is missing. Concrete, bodily, no emotion lists.
DEFAULT_PROBES = [
    "Where in your body do you notice that most, right now?",
    "When did you last feel it this strongly, and what was around you?",
    "If it could change in one way while you sit here, how would you want it to change?",
    "How do you usually carry it through a day?",
]


# =============================================================================
# Questions (owned by node 01; read tolerantly)
# =============================================================================

OPENER_KEYS = ("opening", "opener", "opening_question")
PROBE_KEYS = ("fallback_probes", "probes")


@dataclass
class Questions:
    """Opener + fallback probes. Accepts the shapes node 01 may choose for questions.json:
         {"opening": "...", "fallback_probes": ["...", ...]}                        one language
         {"opening": {"en": "...", "es": "..."}, "fallback_probes": [{"en": ..}, ..]}  per item
         {"en": {"opening": "...", "fallback_probes": [...]}, "es": {...}}            per language
    """
    opener: Any = DEFAULT_OPENER                    # str or {lang: str}
    probes: list = field(default_factory=lambda: list(DEFAULT_PROBES))
    by_lang: dict = field(default_factory=dict)     # lang -> Questions, for the per-language shape

    @classmethod
    def _flat(cls, data: dict) -> "Questions":
        opener = next((data[k] for k in OPENER_KEYS if data.get(k)), DEFAULT_OPENER)
        probes = next((data[k] for k in PROBE_KEYS if data.get(k)), DEFAULT_PROBES)
        return cls(opener=opener, probes=list(probes))

    @classmethod
    def load(cls, path: Path = QUESTIONS_PATH) -> "Questions":
        if not path.exists():
            log.warning("%s not found: using built-in opener and probes", path)
            return cls()
        data = json.loads(path.read_text())
        if not any(k in data for k in OPENER_KEYS + PROBE_KEYS):
            by_lang = {lang: cls._flat(v) for lang, v in data.items() if isinstance(v, dict)}
            if not by_lang:
                log.warning("%s has no opener or probes: using built-ins", path)
                return cls()
            base = by_lang.get("en") or next(iter(by_lang.values()))
            return cls(opener=base.opener, probes=base.probes, by_lang=by_lang)
        return cls._flat(data)

    def for_lang(self, lang: str) -> "Questions":
        return self.by_lang.get(lang) or self.by_lang.get(lang.split("-")[0]) or self

    def opener_text(self, lang: str) -> str:
        return self.pick(self.for_lang(lang).opener, lang)

    def probe_texts(self, lang: str) -> list[str]:
        return [self.pick(p, lang) for p in self.for_lang(lang).probes]

    @staticmethod
    def pick(text: Any, lang: str) -> str:
        if isinstance(text, dict):
            return text.get(lang) or text.get(lang.split("-")[0]) or text.get("en") or next(iter(text.values()))
        return str(text)


# =============================================================================
# Fallback scores
# =============================================================================

def load_fallbacks(directory: Path = FALLBACK_DIR, diagrams: dict | None = None) -> dict[str, dict]:
    """One valid score per active diagram, or raise: we refuse to start without a safety net."""
    diagrams = diagrams if diagrams is not None else mapping.load_diagrams()
    out: dict[str, dict] = {}
    for name in diagrams:
        p = directory / f"{name}.json"
        if not p.exists():
            raise FileNotFoundError(f"missing fallback score {p}")
        out[name] = validate_score(json.loads(p.read_text()))
        if out[name]["diagram"] != name:
            raise ValueError(f"{p} is for diagram {out[name]['diagram']}")
    return out


# =============================================================================
# JSONL log
# =============================================================================

class SessionLog:
    def __init__(self, directory: Path | None = LOG_DIR):
        self.dir = directory
        self._lock = threading.Lock()
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)

    def event(self, session_id: str, event: str, **data: Any) -> None:
        rec = {"t": dt.datetime.now().isoformat(timespec="milliseconds"), "session": session_id,
               "event": event, **data}
        log.debug("log %s %s", event, data)
        if self.dir is None:
            return
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with self._lock:
            with open(self.dir / f"sessions-{dt.date.today():%Y%m%d}.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")


# =============================================================================
# Session
# =============================================================================

class _Abort(Exception):
    pass


class Session:
    def __init__(self, out, voice, interp, *, fallbacks: dict[str, dict], questions: Questions,
                 slog: SessionLog, diagrams: dict | None = None, speed: float = 1.0,
                 rng: random.Random | None = None, lang: str = "en",
                 next_turn_timeout_s: float = safety.NEXT_TURN_TIMEOUT_S,
                 compose_timeout_s: float = safety.COMPOSE_TIMEOUT_S,
                 resurfaced_s: float = safety.RESURFACED_S):
        self.out, self.voice, self.interp = out, voice, interp
        self.fallbacks, self.questions, self.slog = fallbacks, questions, slog
        self.diagrams = diagrams if diagrams is not None else mapping.load_diagrams()
        self.speed = speed
        self.rng = rng or random.Random()
        self.next_turn_timeout_s = next_turn_timeout_s
        self.compose_timeout_s = compose_timeout_s
        self.resurfaced_s = resurfaced_s
        self.default_lang = lang              # opener language, until the first answer says otherwise
        self.id = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        self.state = "idle"
        self.dialogue: dict = {"contract_version": "0.3", "session_id": self.id, "exchanges": []}
        self.score: dict | None = None
        self.score_source: str | None = None
        self.timeline: Timeline | None = None
        self._abort = threading.Event()
        self._panic = threading.Event()
        self._cancel = threading.Event()          # abort OR panic, for waits
        self._lock = threading.Lock()

    # -- control (any thread) ---------------------------------------------------
    def abort(self, reason: str = "operator") -> None:
        with self._lock:
            if self._abort.is_set():
                return
            self._abort.set()
            self._cancel.set()
            state, tl = self.state, self.timeline
        log.warning("abort (%s) during %s", reason, state)
        self.slog.event(self.id, "abort", reason=reason, state=state)
        if state == "asking":
            self.voice.stop()
        if tl is not None:
            tl.leave()

    def panic(self) -> None:
        with self._lock:
            self._panic.set()
            self._cancel.set()
            tl = self.timeline
        if tl is not None:
            tl.panic()
        else:
            self.out.panic()
        self.voice.stop()
        self.slog.event(self.id, "panic", state=self.state)

    # -- run (session thread) -------------------------------------------------------
    def run(self) -> str:
        """Returns the outcome: played | left | aborted | no_answer | panic | error."""
        t0 = time.monotonic()
        self.slog.event(self.id, "session_start", interpreter=getattr(self.interp, "name", None))
        try:
            outcome = self._run()
        except Panicked:
            outcome = "panic"
        except _Abort:
            outcome = "aborted"
            self._to_idle()
        except Exception as e:   # noqa: BLE001 - a bug must not wedge the installation
            log.exception("session error")
            self.slog.event(self.id, "error", error=repr(e), state=self.state)
            self.voice.stop()
            self._to_idle()
            outcome = "error"
        if self._panic.is_set():
            outcome = "panic"
        self.state = "idle"
        self.slog.event(self.id, "session_end", outcome=outcome, seconds=round(time.monotonic() - t0, 2),
                        dialogue=self.dialogue, score_source=self.score_source)
        log.info("session %s ended: %s", self.id, outcome)
        return outcome

    def _run(self) -> str:
        self._set_state("asking")
        if not self._opener():
            self._to_idle()
            return "no_answer"
        self._questionnaire()

        self._set_state("composing")
        self.score, self.score_source = self._compose()
        self.slog.event(self.id, "score", source=self.score_source, score=self.score)

        self._check()
        plan = mapping.map_score(self.score, self.diagrams)
        self.slog.event(self.id, "play", diagram=plan.diagram,
                        movements=[{"phase": m.phase, "at": m.at, "dur_s": round(m.dur_s, 2), **{
                            k: m.numbers[k] for k in ("bpm", "tension", "level", "depth")}} for m in plan.movements])
        with self._lock:
            self.state = "playing"
            self.timeline = Timeline(self.out, speed=self.speed)
            tl = self.timeline
        if self._abort.is_set():
            tl.leave()
        tl.play(plan)
        outcome = "left" if tl.left else "played"

        self.state = "resurfaced"
        self._cancel.wait(self.resurfaced_s / self.speed)   # x cuts the cool-down short
        if self._panic.is_set():
            raise Panicked()
        return outcome

    # -- questionnaire ----------------------------------------------------------------
    def _lang(self) -> str:
        return self.dialogue.get("lang", self.default_lang)

    def _ask(self, question: str) -> dict:
        self._check()
        t0 = time.monotonic()
        try:
            r = call_with_timeout(lambda q: self.voice.ask(q, self._lang()), question, None, self._cancel)
        except Aborted:
            self._check()
            raise
        r["question"] = question
        self.slog.event(self.id, "exchange", question=question, answer=r["answer"], status=r["status"],
                        speech_s=r.get("speech_s"), voice_ok=r["ok"], seconds=round(time.monotonic() - t0, 2))
        return r

    @staticmethod
    def _answered(r: dict) -> bool:
        return r["status"] != "silence" and bool(r["answer"].strip())

    def _append(self, r: dict) -> None:
        ex = {"question": r["question"][:200], "answer": r["answer"], "status": r["status"]}
        if "speech_s" in r:
            ex["speech_s"] = r["speech_s"]
        self.dialogue["exchanges"].append(ex)
        if "lang" not in self.dialogue and r.get("lang") and self._answered(r):
            self.dialogue["lang"] = r["lang"]

    def _opener(self) -> bool:
        q = self.questions.opener_text(self.default_lang)
        for attempt in range(1 + safety.OPENER_SILENCE_RETRIES):
            r = self._ask(q)
            if self._answered(r):
                self._append(r)
                return True
            log.info("opener got no answer (attempt %d)", attempt + 1)
        return False

    def _questionnaire(self) -> None:
        used = 0

        def probe() -> str | None:
            nonlocal used
            texts = self.questions.probe_texts(self._lang())   # language may be known by now
            if used >= len(texts):
                return None
            used += 1
            return texts[used - 1]

        while True:
            asked = len(self.dialogue["exchanges"])
            if asked >= safety.MAX_QUESTIONS:
                log.info("%d questions asked: composing regardless", asked)
                return
            turn, source = self._next_turn()
            if turn is not None:
                self.dialogue["exchanges"][-1]["turn"] = turn
            if turn is not None and turn["action"] == "ask":
                q = turn["question"]
            elif (turn is not None or source == "no_interpreter") and asked >= safety.MIN_QUESTIONS:
                return                                              # compose (or fallback straight away)
            else:
                q = probe()                                         # too early to compose, or turn failed
                source = f"{source}+probe"
                if q is None:
                    if asked >= safety.MIN_QUESTIONS:
                        return
                    q = self.questions.opener_text(self._lang())
            self.slog.event(self.id, "next_question", source=source, question=q, asked=asked)
            self._append(self._ask(q))

    def _next_turn(self) -> tuple[dict | None, str]:
        self._check()
        if self.interp is None:
            return None, "no_interpreter"
        t0 = time.monotonic()
        try:
            turn = call_with_timeout(self.interp.next_turn, self.dialogue, self.next_turn_timeout_s, self._cancel)
            validate_turn(turn)
            source = "turn"
            err = None
        except Aborted:
            self._check()
            raise
        except Exception as e:   # noqa: BLE001 - timeout, InterpretationError, TurnError, bugs
            turn, source, err = None, "turn_error", repr(e)
            log.warning("next_turn failed: %s", e)
        self.slog.event(self.id, "turn", source=source, turn=turn, error=err,
                        seconds=round(time.monotonic() - t0, 2))
        return turn, source

    # -- compose ------------------------------------------------------------------------
    def _hypothesis_diagram(self) -> str | None:
        for e in reversed(self.dialogue["exchanges"]):
            d = (e.get("turn") or {}).get("hypothesis", {}).get("diagram")
            if d in self.fallbacks:
                return d
        return None

    def _compose(self) -> tuple[dict, str]:
        self._check()
        t0 = time.monotonic()
        err = None
        if self.interp is not None:
            try:
                score = call_with_timeout(self.interp.compose, self.dialogue, self.compose_timeout_s, self._cancel)
                validate_score(score)
                self.slog.event(self.id, "compose", ok=True, seconds=round(time.monotonic() - t0, 2))
                return score, "composed"
            except Aborted:
                self._check()
                raise
            except ContractError as e:
                err = e.errors
            except Exception as e:   # noqa: BLE001
                err = repr(e)
        else:
            err = "no interpreter"
        diagram = self._hypothesis_diagram() or self.rng.choice(sorted(self.fallbacks))
        log.warning("compose failed (%s): fallback score for %s", err, diagram)
        self.slog.event(self.id, "compose", ok=False, error=err, fallback=diagram,
                        seconds=round(time.monotonic() - t0, 2))
        return self.fallbacks[diagram], f"fallback:{diagram}"

    # -- helpers ----------------------------------------------------------------------------
    def _check(self) -> None:
        if self._panic.is_set():
            raise Panicked()
        if self._abort.is_set():
            raise _Abort()

    def _set_state(self, state: str) -> None:
        with self._lock:
            self.state = state
        if not self.out.send("/pathos/state", state):
            raise Panicked()

    def _to_idle(self) -> None:
        self.state = "idle"
        if not self._panic.is_set():
            self.out.send("/pathos/state", "idle")


# =============================================================================
# Controller
# =============================================================================

class Controller:
    """Keys and sensor → sessions. `handle_key` is thread-safe; `loop` runs on the main thread."""

    def __init__(self, make_session: Callable[[], Session], out, voice, sensor, *, once: bool = False):
        self.make_session = make_session
        self.out, self.voice, self.sensor = out, voice, sensor
        self.once = once
        self.session: Session | None = None
        self.thread: threading.Thread | None = None
        self.outcomes: list[str] = []
        self.keys: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._gone_reported = False

    def handle_key(self, ch: str) -> None:
        self.keys.put(ch)

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def start_session(self, reason: str) -> bool:
        if self.running:
            log.info("start (%s) ignored: session %s is %s", reason, self.session.id, self.session.state)
            return False
        self.out.reset()
        self.session = self.make_session()
        self._gone_reported = False
        log.info("session %s start (%s)", self.session.id, reason)

        def run(s: Session = self.session) -> None:
            self.outcomes.append(s.run())

        self.thread = threading.Thread(target=run, name=f"session-{self.session.id}", daemon=True)
        self.thread.start()
        return True

    def panic(self) -> None:
        log.warning("PANIC")
        if self.running and self.session is not None:
            self.session.panic()
        else:
            self.out.panic()
            self.voice.stop()

    def _on_key(self, ch: str) -> None:
        if ch in ("p", "P", " "):
            self.panic()
        elif ch in ("s", "S"):
            self.start_session("key s")
        elif ch in ("x", "X"):
            if self.running and self.session is not None:
                self.session.abort("key x")
            else:
                log.info("x: nothing to abort")

    def _poll_sensor(self) -> None:
        self.sensor.check_alarm()
        if not self.sensor.alive():
            return
        if not self.running and self.sensor.present_for() >= safety.PRESENT_HOLD_S:
            self.start_session("sensor present")
        elif self.running and self.session is not None and not self._gone_reported \
                and self.session.state in ("asking", "composing", "playing") \
                and self.sensor.absent_for() >= safety.VISITOR_GONE_S:
            self._gone_reported = True
            self.session.abort("sensor absent")

    def loop(self, poll_s: float = 0.05) -> None:
        was_running = False
        while not self._stop.is_set():
            try:
                self._on_key(self.keys.get(timeout=poll_s))
            except queue.Empty:
                pass
            self._poll_sensor()
            if was_running and not self.running and self.once:
                return
            was_running = self.running
