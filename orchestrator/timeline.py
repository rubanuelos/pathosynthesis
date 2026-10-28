"""Plays a mapped score as OSC (contract v0.3 §6). Time-driven only: no gesture gating.

    /pathos/diagram/select <diagram>              once, when the score is ready
    /pathos/global/lag 3 ; /pathos/global/master 1.0    (§5.1: movements play at master 1.0)
    per movement:
        /pathos/global/lag <transition lag>
        /pathos/state <phase> ; /pathos/diagram/position <diagram at level levels depth>
        /pathos/vial/chord ; /pathos/vial/voices ; /pathos/chair/heartbeat ; /pathos/chair/drone
        hold for dur_s
    end (§6.5): lag 6 ; heartbeat intensity 0 ; drone amp 0 ; master 0 ; /pathos/state idle

Visitor left (§6.4), via leave(): during mirror/dwell/transform -> enter the score's `resurface`
movement with lag 6, hold it for that glide (6 s), then the end sequence. During resurface ->
end sequence now. Panic (any thread) -> OscOut.panic() and Panicked is raised.
Any crash -> panic.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from . import mapping
from .mapping import MappedMovement, Plan

log = logging.getLogger("pathos.timeline")

POLL_S = 0.05


class Panicked(RuntimeError):
    pass


class _Left(Exception):
    pass


class Timeline:
    def __init__(self, out, *, speed: float = 1.0,
                 on_movement: Callable[[MappedMovement], None] | None = None):
        if speed < 1.0:
            raise ValueError("speed must be >= 1 (rehearsal compression only)")
        self.out = out
        self.speed = speed
        self.on_movement = on_movement
        self._panic = threading.Event()
        self._leave = threading.Event()
        self.current: MappedMovement | None = None
        self.left = False

    # -- control (any thread) ---------------------------------------------------
    def panic(self) -> None:
        self._panic.set()
        self.out.panic()

    def leave(self) -> None:
        """Visitor left: wrap up gracefully (§6.4)."""
        self._leave.set()

    # -- play ---------------------------------------------------------------------
    def play(self, plan: Plan) -> None:
        """Blocking. Returns after the end sequence. Raises Panicked if stopped by panic."""
        try:
            self._send("/pathos/diagram/select", plan.diagram)
            self._send("/pathos/global/lag", mapping.MASTER_LAG_S / self.speed)
            self._send("/pathos/global/master", mapping.MOVEMENT_MASTER)
            try:
                for mv in plan.movements:
                    self._enter(mv, mv.lag_s)
                    self._hold(mv.dur_s)
            except _Left:
                self.left = True
                self._leave_sequence(plan)
            self._end(self.current or plan.movements[-1])
        except Panicked:
            raise
        except BaseException:
            log.exception("timeline stopped by an error: panicking")
            self.panic()
            raise

    def _leave_sequence(self, plan: Plan) -> None:
        last = plan.movements[-1]
        if self.current is not None and self.current.phase == "resurface":
            log.info("visitor left during resurface: ending now")
            return
        log.info("visitor left during %s: jumping to resurface", self.current.phase if self.current else "start")
        self._leave.clear()
        self._enter(last, mapping.LEAVE_LAG_S, interruptible=False)
        self._hold(mapping.LEAVE_LAG_S, interruptible=False)

    def _enter(self, mv: MappedMovement, lag_s: float, interruptible: bool = True) -> None:
        self._check(interruptible)
        log.info("movement %d: %s at %s (%.1f s, lag %.1f s)", mv.index, mv.phase, mv.at, mv.dur_s, lag_s)
        self.current = mv
        if self.on_movement:
            self.on_movement(mv)
        self._send("/pathos/global/lag", lag_s / self.speed)
        self._send("/pathos/state", mv.phase)
        self._send(mv.position.address, *mv.position.args)
        for m in mv.sets:
            self._send(m.address, *m.args)

    def _end(self, last: MappedMovement) -> None:
        self._check(False)
        self._send("/pathos/global/lag", mapping.END_LAG_S / self.speed)
        for m in mapping.end_sets(last):
            self._send(m.address, *m.args)
        self._send("/pathos/global/master", 0.0)
        self._send("/pathos/state", "idle")
        log.info("score finished%s", " (visitor left)" if self.left else "")

    # -- helpers --------------------------------------------------------------------
    def _send(self, address: str, *args) -> None:
        if not self.out.send(address, *args):
            raise Panicked()

    def _check(self, interruptible: bool) -> None:
        if self._panic.is_set() or self.out.panicked:
            raise Panicked()
        if interruptible and self._leave.is_set():
            raise _Left()

    def _hold(self, score_seconds: float, interruptible: bool = True) -> None:
        deadline = time.monotonic() + score_seconds / self.speed
        while True:
            self._check(interruptible)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._panic.wait(min(POLL_S, remaining))   # leave is polled every POLL_S
