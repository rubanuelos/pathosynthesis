"""Adapters for node 01's Python API (contract v0.3 §2.5): next_turn(dialogue) -> turn, compose(dialogue) -> score.

LiveInterpreter      imports the real `interpretation` package (next_turn / compose at package level,
                     or in interpretation.interpret).
ScriptedInterpreter  replays the turns stored in a dialogue file (contract/examples/dialogue_*.json).
                     compose() returns contract/examples/score_<diagram>_*.json for the last hypothesis
                     diagram if one exists, otherwise raises, so the session's fallback path runs.

Either may raise anything; the session treats every exception as InterpretationError and falls back.
call_with_timeout() enforces the §2.2.6 timeouts without trusting the callee to honour them.
"""
from __future__ import annotations

import copy
import importlib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("pathos.interp")

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "contract" / "examples"


class InterpretationError(RuntimeError):
    pass


class Aborted(Exception):
    """The wait was cut short by abort/panic."""


def call_with_timeout(fn: Callable[[Any], Any], arg: Any, timeout: float | None,
                      cancel: threading.Event | None = None, poll: float = 0.05) -> Any:
    """Run fn(arg) in a daemon thread. Raises TimeoutError, Aborted, or whatever fn raised.

    A timed-out call is abandoned, not killed; its late result is discarded.
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def work() -> None:
        try:
            box["result"] = fn(arg)
        except BaseException as e:   # noqa: BLE001 - reported to caller
            box["error"] = e
        finally:
            done.set()

    threading.Thread(target=work, name=f"call-{getattr(fn, '__name__', 'fn')}", daemon=True).start()
    waited = 0.0
    while not done.wait(poll):
        waited += poll
        if cancel is not None and cancel.is_set():
            raise Aborted()
        if timeout is not None and waited >= timeout:
            raise TimeoutError(f"{getattr(fn, '__name__', 'call')} exceeded {timeout:.1f} s")
    if "error" in box:
        raise box["error"]
    return box["result"]


class LiveInterpreter:
    name = "live"

    def __init__(self) -> None:
        mod = importlib.import_module("interpretation")
        if not (hasattr(mod, "next_turn") and hasattr(mod, "compose")):
            mod = importlib.import_module("interpretation.interpret")
        self._next_turn = mod.next_turn
        self._compose = mod.compose

    def next_turn(self, dialogue: dict) -> dict:
        return self._next_turn(copy.deepcopy(dialogue))

    def compose(self, dialogue: dict) -> dict:
        return self._compose(copy.deepcopy(dialogue))


class ScriptedInterpreter:
    name = "scripted"

    def __init__(self, scripted_dialogue: dict, examples_dir: Path = EXAMPLES_DIR):
        self.turns = [e.get("turn") for e in scripted_dialogue["exchanges"]]
        self.examples_dir = examples_dir

    def next_turn(self, dialogue: dict) -> dict:
        i = len(dialogue["exchanges"]) - 1
        if i >= len(self.turns) or self.turns[i] is None:
            raise InterpretationError(f"no scripted turn after answer {i + 1}")
        return copy.deepcopy(self.turns[i])

    def compose(self, dialogue: dict) -> dict:
        hyp = next((e["turn"]["hypothesis"] for e in reversed(dialogue["exchanges"])
                    if e.get("turn") and e["turn"]["hypothesis"].get("diagram")), None)
        if hyp is None:
            raise InterpretationError("scripted compose: no hypothesis diagram")
        stem = hyp["diagram"].replace("-", "_")
        matches = sorted(self.examples_dir.glob(f"score_{stem}_*.json"))
        if not matches:
            raise InterpretationError(f"scripted compose: no example score for {hyp['diagram']}")
        log.info("scripted compose -> %s", matches[0].name)
        return json.loads(matches[0].read_text())


def make_interpreter(kind: str, scripted_dialogue: dict | None = None):
    """kind: live | scripted | auto (live if importable, else scripted, else None)."""
    if kind in ("live", "auto"):
        try:
            return LiveInterpreter()
        except Exception as e:   # noqa: BLE001
            if kind == "live":
                raise
            log.warning("interpretation package not importable (%s)", e)
    if kind in ("scripted", "auto") and scripted_dialogue is not None:
        return ScriptedInterpreter(scripted_dialogue)
    if kind == "scripted":
        raise ValueError("scripted interpretation needs --dialogue")
    return None
