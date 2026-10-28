"""Safety limits (contract v0.3 §7). Enforced in code, never by prompt.

- limit(): every outgoing OSC message passes here (via osc_io.OscOut.send).
  Checks the address is in contract §4, checks arity and types, clamps every
  number to its §4 range, then applies install-time ceilings from calibration.json.
  Unknown addresses raise: the orchestrator never invents OSC.
- Session bounds and timeouts (§2.2, §7.4) live here so they are in one place.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Sequence

log = logging.getLogger("pathos.safety")

# --- §2.2 / §7.4 session bounds -------------------------------------------
MIN_QUESTIONS = 2
MAX_QUESTIONS = 5
NEXT_TURN_TIMEOUT_S = 6.0
COMPOSE_TIMEOUT_S = 10.0
OPENER_SILENCE_RETRIES = 1
RESURFACED_S = 20.0

# --- §4 / §7.1 watchdogs ------------------------------------------------------
KEEPALIVE_HZ = 4.0
SC_WATCHDOG_S = 5.0              # SC fades master if no keepalive for this long (SC side)
SENSOR_TIMEOUT_S = 3.0
PRESENT_HOLD_S = 2.0             # present 1 held this long while idle -> start (--sensor)
VISITOR_GONE_S = 15.0            # present 0 this long -> visitor left (--sensor)

CALIBRATION_PATH = Path(__file__).with_name("calibration.json")

STATES = {"idle", "asking", "composing", "mirror", "dwell", "transform", "resurface"}
MAX_VOICE_PAIRS = 6
VOICE_RATIO_RANGE = (0.25, 8.0)  # sanity only; contract leaves the ratio open


@dataclass(frozen=True)
class Calibration:
    """Install-time ceilings (§7.3), 0..1. SC also holds its own calibrated max and limiter;
    these are the orchestrator's belt to SC's braces. Edit calibration.json on site, not code."""
    master_max: float = 1.0      # ceiling on /pathos/global/master (which is "0–1 of the calibrated max")
    chair_max: float = 1.0       # ceiling on heartbeat intensity and drone amp

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Calibration":
        p = Path(path) if path else CALIBRATION_PATH
        if not p.exists():
            log.warning("no calibration file at %s, using defaults", p)
            return cls()
        data = json.loads(p.read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known - {"_comment"}
        if unknown:
            raise ValueError(f"unknown calibration keys: {sorted(unknown)}")
        cal = cls(**{k: float(v) for k, v in data.items() if k in known})
        for f in fields(cal):
            v = getattr(cal, f.name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"calibration {f.name}={v} outside 0..1")
        return cal


class UnknownAddress(ValueError):
    pass


# fixed-arity numeric addresses: one (lo, hi) per float arg
RANGES: dict[str, tuple[tuple[float, float], ...]] = {
    "/pathos/global/lag": ((0.0, 30.0),),
    "/pathos/global/master": ((0.0, 1.0),),
    "/pathos/vial/chord": ((40.0, 400.0), (0.0, 1.0), (0.0, 1.0), (0.0, 1.0)),
    "/pathos/chair/heartbeat": ((40.0, 110.0), (0.0, 1.0), (0.0, 1.0)),
    "/pathos/chair/drone": ((25.0, 80.0), (0.0, 1.0)),
    "/pathos/keepalive": (),
    "/pathos/panic": (),
}
SPECIAL = {"/pathos/state", "/pathos/diagram/select", "/pathos/diagram/position", "/pathos/vial/voices"}
ADDRESSES = set(RANGES) | SPECIAL


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _name(v: object, what: str) -> str:
    if not isinstance(v, str) or not v or len(v) > 64:
        raise ValueError(f"{what} must be a short non-empty string, got {v!r}")
    return v


def limit(address: str, args: Sequence, cal: Calibration) -> tuple:
    """Return safe args for `address`, or raise. Idempotent, so re-sending is safe."""
    if address not in ADDRESSES:
        raise UnknownAddress(f"{address} is not in contract §4")

    if address == "/pathos/state":
        if len(args) != 1 or args[0] not in STATES:
            raise ValueError(f"/pathos/state needs one of {sorted(STATES)}, got {args!r}")
        return (args[0],)

    if address == "/pathos/diagram/select":
        if len(args) != 1:
            raise ValueError(f"{address} expects 1 arg, got {len(args)}")
        return (_name(args[0], "diagram"),)

    if address == "/pathos/diagram/position":
        if len(args) != 5:
            raise ValueError(f"{address} expects (diagram, at, level, levels, depth), got {args!r}")
        diagram, at, level, levels, depth = args
        if isinstance(level, bool) or isinstance(levels, bool) or not isinstance(level, int) \
                or not isinstance(levels, int):
            raise ValueError(f"{address}: level and levels must be ints, got {level!r}, {levels!r}")
        if levels < 1 or not 0 <= level < levels:
            raise ValueError(f"{address}: level {level} outside 0..{levels - 1}")
        return (_name(diagram, "diagram"), _name(at, "at"), level, levels, _clamp(float(depth), 0.0, 1.0))

    if address == "/pathos/vial/voices":
        vals = [float(a) for a in args]
        if len(vals) % 2 or not vals:
            raise ValueError(f"{address} needs (ratio, amp) pairs, got {len(vals)} values")
        if len(vals) > 2 * MAX_VOICE_PAIRS:
            log.warning("%s: %d pairs, truncating to %d", address, len(vals) // 2, MAX_VOICE_PAIRS)
            vals = vals[: 2 * MAX_VOICE_PAIRS]
        out: list[float] = []
        for r, a in zip(vals[0::2], vals[1::2]):
            out += [_clamp(r, *VOICE_RATIO_RANGE), _clamp(a, 0.0, 1.0)]
        return tuple(out)

    ranges = RANGES[address]
    if len(args) != len(ranges):
        raise ValueError(f"{address} expects {len(ranges)} args, got {len(args)}")
    vals = [float(a) for a in args]
    out = [_clamp(v, lo, hi) for v, (lo, hi) in zip(vals, ranges)]
    if out != vals:
        log.warning("clamped %s %s -> %s", address, vals, out)

    if address == "/pathos/global/master":
        out[0] = min(out[0], cal.master_max)
    elif address == "/pathos/chair/heartbeat":
        out[2] = min(out[2], cal.chair_max)
    elif address == "/pathos/chair/drone":
        out[1] = min(out[1], cal.chair_max)
    return tuple(out)
