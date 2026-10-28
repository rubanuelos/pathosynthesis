"""voice/engine.py — what /ask and /stop actually do.

VoiceService   single-flight wrapper: one /ask at a time; a new /ask preempts
               the running one; /stop cancels it. Engines only need to honour
               a threading.Event.
FakeEngine     keyboard or scripted answers, no audio, stdlib only (--fake).
RealEngine     TTS on R -> mic + VAD end-of-turn -> faster-whisper.

Response shape (contract §2.4):
    {"answer": str, "status": "ok"|"silence"|"timeout", "speech_s": float, "lang": str}
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterator, Protocol

from .config import Config

log = logging.getLogger("voice")

ANSWER_MAX_CHARS = 2000  # dialogue.schema.json exchanges[].answer.maxLength
TEXT_MAX_CHARS = 500     # questions are <= 200 (turn schema); a title may be spoken too


class Stopped(Exception):
    """The ask was cut by /stop or preempted by a newer /ask."""


class BadRequest(ValueError):
    pass


@dataclass
class AskRequest:
    text: str
    lang: str
    listen_max_s: float
    end_silence_s: float

    @classmethod
    def parse(cls, body: object, cfg: Config) -> "AskRequest":
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise BadRequest("'text' must be a non-empty string")
        text = text.strip()[:TEXT_MAX_CHARS]
        lang = body.get("lang") or cfg.tts.default_lang
        if not isinstance(lang, str) or len(lang) > 16:
            raise BadRequest("'lang' must be a short language tag")
        try:
            listen_max_s = float(body.get("listen_max_s", 45))
            end_silence_s = float(body.get("end_silence_s", 2.5))
        except (TypeError, ValueError) as exc:
            raise BadRequest("listen_max_s / end_silence_s must be numbers") from exc
        L = cfg.listen
        # listen_max_s <= 0: speak only, do not listen (see contract change request).
        if listen_max_s > 0:
            listen_max_s = min(max(listen_max_s, 1.0), L.listen_max_cap_s)
        else:
            listen_max_s = 0.0
        end_silence_s = min(max(end_silence_s, L.end_silence_min_s), L.end_silence_max_s)
        return cls(text, lang.lower(), listen_max_s, end_silence_s)


def result(answer: str, status: str, speech_s: float, lang: str) -> dict:
    return {
        "answer": answer[:ANSWER_MAX_CHARS],
        "status": status,
        "speech_s": round(max(speech_s, 0.0), 2),
        "lang": lang,
    }


class Engine(Protocol):
    def ask(self, req: AskRequest, cancel: threading.Event) -> dict: ...
    def ready(self) -> bool: ...


# --------------------------------------------------------------------------- #
# Single-flight service
# --------------------------------------------------------------------------- #
class VoiceService:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._token_lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._cancel: threading.Event | None = None

    def ready(self) -> bool:
        return self.engine.ready()

    def ask(self, req: AskRequest) -> dict:
        cancel = threading.Event()
        with self._token_lock:
            if self._cancel is not None:
                log.info("new /ask preempts the running one")
                self._cancel.set()
            self._cancel = cancel
        with self._run_lock:  # wait for a preempted ask to unwind (it fades out fast)
            try:
                if cancel.is_set():
                    raise Stopped()
                return self.engine.ask(req, cancel)
            finally:
                with self._token_lock:
                    if self._cancel is cancel:
                        self._cancel = None

    def stop(self) -> bool:
        with self._token_lock:
            if self._cancel is None:
                return False
            self._cancel.set()
            return True


# --------------------------------------------------------------------------- #
# Fake engine (--fake)
# --------------------------------------------------------------------------- #
FAKE_HELP = (
    "answer + Enter  |  empty line = silence  |  '/timeout <text>' = timeout  |  "
    "'@es <text>' = answer in Spanish"
)


class FakeEngine:
    """Answers from the keyboard (or a script file) instead of the mic.

    Line syntax (keyboard and script):
        some answer            -> status ok
        (empty line)           -> status silence
        /timeout some answer   -> status timeout
        @es una respuesta      -> lang es (any 2-5 letter tag)
    A script that runs out answers silence. No keyboard answer within
    listen_max_s answers silence, like a visitor who never speaks.
    """

    def __init__(self, cfg: Config, script: list[str] | None = None,
                 delay_s: float = 0.5, tts=None):
        self.cfg = cfg
        self.delay_s = delay_s
        self.tts = tts            # optional: speak questions for real with --speak
        self._script: Iterator[str] | None = iter(script) if script is not None else None
        self._lines: queue.Queue[str] = queue.Queue()
        if self._script is None:
            threading.Thread(target=self._read_stdin, daemon=True, name="stdin").start()

    def ready(self) -> bool:
        return True

    def _read_stdin(self) -> None:
        for line in sys.stdin:
            self._lines.put(line.rstrip("\n"))

    @staticmethod
    def parse_line(line: str, default_lang: str) -> dict:
        line = line.strip()
        lang = default_lang
        status = "ok"
        if line.startswith("@"):
            tag, _, rest = line.partition(" ")
            if 2 <= len(tag) - 1 <= 5 and tag[1:].replace("-", "").isalpha():
                lang, line = tag[1:].lower(), rest.strip()
        if line.startswith("/timeout"):
            status, line = "timeout", line[len("/timeout"):].strip()
        if not line:
            return result("", "silence", 0.0, lang)
        speech_s = 0.45 * len(line.split())  # rough speaking time
        return result(line, status, speech_s, lang)

    def ask(self, req: AskRequest, cancel: threading.Event) -> dict:
        print(f"\n[voice] Q ({req.lang}): {req.text}", flush=True)
        if self.tts is not None:
            self.tts.speak(req.text, req.lang, cancel)
        if cancel.is_set():
            raise Stopped()
        if req.listen_max_s <= 0:
            return result("", "silence", 0.0, req.lang)

        if self._script is not None:
            if cancel.wait(self.delay_s):
                raise Stopped()
            line = next(self._script, "")
            print(f"[voice] A: {line!r}", flush=True)
            return self.parse_line(line, req.lang)

        while not self._lines.empty():  # drop anything typed before the question
            self._lines.get_nowait()
        print(f"[voice] ({FAKE_HELP})\n> ", end="", flush=True)
        deadline = time.monotonic() + req.listen_max_s
        while True:
            if cancel.is_set():
                print("\n[voice] stopped", flush=True)
                raise Stopped()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print("\n[voice] no answer within listen_max_s -> silence", flush=True)
                return result("", "silence", 0.0, req.lang)
            try:
                line = self._lines.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            return self.parse_line(line, req.lang)


# --------------------------------------------------------------------------- #
# Real engine
# --------------------------------------------------------------------------- #
class RealEngine:
    def __init__(self, cfg: Config):
        # Heavy imports only here, so --fake needs nothing beyond the stdlib.
        from . import audio, listen, stt, tts

        self.cfg = cfg
        self._listen = listen
        audio.check_output_routing(cfg.output)   # refuses L / missing channel
        audio.check_input(cfg.input)
        self.tts = tts.make(cfg.tts, cfg.output)
        self.stt = stt.Transcriber(cfg.stt)
        self.stt.warmup()
        self._cue = audio.load_cue(cfg.output.listen_cue)
        self._ready = True
        log.info("real engine ready (tts=%s, stt=%s)", cfg.tts.engine, cfg.stt.model)

    def ready(self) -> bool:
        return self._ready

    def ask(self, req: AskRequest, cancel: threading.Event) -> dict:
        t0 = time.monotonic()
        self.tts.speak(req.text, req.lang, cancel)
        if cancel.is_set():
            raise Stopped()
        if req.listen_max_s <= 0:
            return result("", "silence", 0.0, req.lang)
        if self._cue is not None:
            self.tts.play_buffer(*self._cue, cancel)
        if cancel.wait(self.cfg.listen.delay_s):
            raise Stopped()

        t1 = time.monotonic()
        turn = self._listen.capture_turn(self.cfg, req.end_silence_s, req.listen_max_s, cancel)
        if turn.status == "stopped":
            raise Stopped()
        t2 = time.monotonic()

        answer, lang = "", req.lang
        if turn.audio is not None:
            answer, lang = self.stt.transcribe(turn.audio, hint=req.lang)
            turn.audio = None  # discard the recording (contract §2.4, §7.5)
        if cancel.is_set():
            raise Stopped()
        status = turn.status if answer else "silence"
        t3 = time.monotonic()
        log.info("ask: speak %.1fs | listen %.1fs (%s, speech %.1fs) | stt %.1fs -> %s/%s%s",
                 t1 - t0, t2 - t1, turn.status, turn.speech_s, t3 - t2, status, lang,
                 f" {answer!r}" if self.cfg.stt.log_transcripts else "")
        return result(answer, status, turn.speech_s if answer else 0.0, lang)
