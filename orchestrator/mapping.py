"""Semantic -> numeric mapping (contract v0.3 §5).

THIS IS THE ONLY PLACE IN THE SYSTEM WHERE SCORE WORDS BECOME NUMBERS.
Pure functions of (score, diagrams.json). Clamping to contract ranges and
install ceilings happens later, once, in safety.limit() inside the OSC sender.

What a diagram `level` sounds like is composition, decided in the diagram's
SuperCollider patch. This module only passes level / levels / depth through.

Orchestrator-side choices the contract leaves open (flagged for 00):
  * transform interpolation point: with k transforms, the j-th (0-based) uses
    t = (j + 1) / (k + 1) between `mixture` (t=0) and `destination` (t=1);
  * a color interval that lands on ratio 1.0 (`unison`) is sent as its own voice,
    as the contract says "root, then the color intervals in order".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

DIAGRAMS_PATH = Path(__file__).resolve().parents[1] / "contract" / "diagrams.json"

# --- §5.1 heartbeat ----------------------------------------------------------
TEMPO_BPM = {"very_slow": 48.0, "slow": 56.0, "resting": 66.0, "elevated": 84.0, "racing": 100.0}
REGULARITY_IRREGULARITY = {"steady": 0.0, "uneven": 0.35, "erratic": 0.75}
WEIGHT_INTENSITY = {"faint": 0.3, "present": 0.6, "heavy": 0.9}

# --- §5.1 chord --------------------------------------------------------------
REGISTER_ROOT_HZ = {"low": 55.0, "mid": 110.0, "high": 220.0}
DENSITY = {"sparse": 0.2, "medium": 0.5, "thick": 0.85}
BRIGHTNESS = {"dark": 0.1, "veiled": 0.35, "clear": 0.6, "bright": 0.9}
INTERVAL_RATIO = {
    "unison": 1 / 1, "min2": 16 / 15, "maj2": 9 / 8, "min3": 6 / 5, "maj3": 5 / 4,
    "p4": 4 / 3, "tritone": 45 / 32, "p5": 3 / 2, "min6": 8 / 5, "maj6": 5 / 3,
    "min7": 9 / 5, "maj7": 15 / 8, "octave": 2 / 1,
}
ROOT_AMP = 1.0
COLOR_AMPS = (0.7, 0.5, 0.35, 0.25, 0.18)   # by prominence order

# --- §5.1 tension ------------------------------------------------------------
INTERVAL_DISSONANCE = {
    "unison": 0.0, "octave": 0.0, "p5": 0.1, "p4": 0.15, "maj3": 0.25, "min3": 0.3, "maj6": 0.3,
    "min6": 0.4, "maj2": 0.55, "min7": 0.55, "tritone": 0.8, "maj7": 0.8, "min2": 1.0,
}
TENSION_DISSONANCE_SHARE = 0.6
TENSION_BALANCE_SHARE = 0.4

# --- §5.1 chair drone --------------------------------------------------------
DRONE_FREQ_HZ = {"low": 27.5, "mid": 41.25, "high": 55.0}
DRONE_AMP = {"faint": 0.15, "present": 0.3, "heavy": 0.45}

# --- §5.1 transition / master --------------------------------------------------
TRANSITION_LAG_S = {"cut": 0.2, "glide": 4.0, "slow_glide": 12.0}
MOVEMENT_MASTER = 1.0
MASTER_LAG_S = 3.0

# --- §5.2 durations ----------------------------------------------------------
LENGTH_TOTAL_S = {"brief": 120.0, "medium": 180.0, "long": 270.0}
SPAN_WEIGHT = {"short": 1.0, "medium": 2.0, "long": 3.0}
MOVEMENT_MIN_S = 15.0
MOVEMENT_MAX_S = 120.0

# --- §6.4 / §6.5 ending --------------------------------------------------------
LEAVE_LAG_S = 6.0
END_LAG_S = 6.0


# =============================================================================
# diagrams.json
# =============================================================================

@dataclass(frozen=True)
class Diagram:
    name: str
    levels: int                  # max level + 1
    positions: dict[str, int]    # position name -> level


@lru_cache(maxsize=4)
def load_diagrams(path: str | Path = DIAGRAMS_PATH) -> dict[str, Diagram]:
    """Active diagrams only."""
    data = json.loads(Path(path).read_text())
    out: dict[str, Diagram] = {}
    for name, d in data["diagrams"].items():
        if not d.get("active"):
            continue
        pos = {p["name"]: int(p["level"]) for p in d["positions"]}
        if not pos:
            raise ValueError(f"diagrams.json: active diagram {name} has no positions")
        out[name] = Diagram(name=name, levels=max(pos.values()) + 1, positions=pos)
    return out


def position(diagrams: dict[str, Diagram], diagram: str, at: str) -> tuple[int, int, float]:
    """-> (level, levels, depth). depth = level / (levels - 1); 0 for a one-level diagram."""
    d = diagrams[diagram]
    level = d.positions[at]
    depth = level / (d.levels - 1) if d.levels > 1 else 0.0
    return level, d.levels, depth


# =============================================================================
# per-movement pure functions
# =============================================================================

def heartbeat(hb: dict) -> tuple[float, float, float]:
    """-> (bpm, irregularity, intensity)"""
    return TEMPO_BPM[hb["tempo"]], REGULARITY_IRREGULARITY[hb["regularity"]], WEIGHT_INTENSITY[hb["weight"]]


def chord_scalars(ch: dict) -> tuple[float, float, float]:
    """-> (root_hz, density, brightness)"""
    return REGISTER_ROOT_HZ[ch["register"]], DENSITY[ch["density"]], BRIGHTNESS[ch["brightness"]]


def voices(color: list[str]) -> list[tuple[float, float]]:
    """Root (1.0, 1.0), then each color interval in prominence order with amps 0.7, 0.5, 0.35, 0.25, 0.18."""
    return [(1.0, ROOT_AMP)] + [(INTERVAL_RATIO[c], COLOR_AMPS[i]) for i, c in enumerate(color[:len(COLOR_AMPS)])]


def balance(mixture: list[dict]) -> float:
    """1 - (w1 - w2) for the two largest weights; 0 with a single emotion."""
    w = sorted((float(e["weight"]) for e in mixture), reverse=True)
    if len(w) < 2:
        return 0.0
    return 1.0 - (w[0] - w[1])


def tension(color: list[str], mixture: list[dict]) -> float:
    diss = sum(INTERVAL_DISSONANCE[c] for c in color) / len(color)
    t = TENSION_DISSONANCE_SHARE * diss + TENSION_BALANCE_SHARE * balance(mixture)
    return min(1.0, max(0.0, t))


def interpolate(a: list[dict], b: list[dict], t: float) -> list[dict]:
    """Linear blend of two mixtures; an emotion missing on one side counts as weight 0."""
    if a is b:
        return a
    wa = {e["emotion"]: float(e["weight"]) for e in a}
    wb = {e["emotion"]: float(e["weight"]) for e in b}
    names = list(dict.fromkeys([*wa, *wb]))
    blended = [{"emotion": n, "weight": (1 - t) * wa.get(n, 0.0) + t * wb.get(n, 0.0)} for n in names]
    return [e for e in blended if e["weight"] > 0] or blended[:1]


def active_mixtures(score: dict) -> list[list[dict]]:
    """Active mixture per movement (§5.1 tension)."""
    mix = score["mixture"]
    dest = score.get("destination") or mix
    phases = [m["phase"] for m in score["movements"]]
    k = phases.count("transform")
    out, j = [], 0
    for p in phases:
        if p in ("mirror", "dwell"):
            out.append(mix)
        elif p == "resurface":
            out.append(dest)
        else:
            j += 1
            out.append(interpolate(mix, dest, j / (k + 1)))
    return out


def drone(chord: dict, hb: dict) -> tuple[float, float]:
    """-> (freq_hz, amp)"""
    return DRONE_FREQ_HZ[chord["register"]], DRONE_AMP[hb["weight"]]


def durations(length: str, spans: list[str]) -> list[float]:
    """§5.2: total · weight / Σweights, each clamped to 15–120 s."""
    total = LENGTH_TOTAL_S[length]
    w = [SPAN_WEIGHT[s] for s in spans]
    sw = sum(w)
    return [min(MOVEMENT_MAX_S, max(MOVEMENT_MIN_S, total * x / sw)) for x in w]


def lag(transition: str) -> float:
    return TRANSITION_LAG_S[transition]


# =============================================================================
# whole score
# =============================================================================

@dataclass(frozen=True)
class Msg:
    address: str
    args: tuple


@dataclass
class MappedMovement:
    index: int
    phase: str
    at: str
    dur_s: float
    lag_s: float
    position: Msg                         # /pathos/diagram/position, sent right after /pathos/state
    sets: list[Msg] = field(default_factory=list)   # chord, voices, heartbeat, drone (in that order)
    numbers: dict[str, Any] = field(default_factory=dict)   # for logs


@dataclass
class Plan:
    diagram: str
    movements: list[MappedMovement]

    @property
    def total_s(self) -> float:
        return sum(m.dur_s for m in self.movements)


def map_movement(i: int, mv: dict, diagram: str, mixture: list[dict], dur_s: float,
                 diagrams: dict[str, Diagram]) -> MappedMovement:
    bpm, irr, intensity = heartbeat(mv["heartbeat"])
    root, dens, bright = chord_scalars(mv["chord"])
    tens = tension(mv["chord"]["color"], mixture)
    vox = voices(mv["chord"]["color"])
    d_freq, d_amp = drone(mv["chord"], mv["heartbeat"])
    level, levels, depth = position(diagrams, diagram, mv["at"])
    return MappedMovement(
        index=i, phase=mv["phase"], at=mv["at"], dur_s=dur_s, lag_s=lag(mv["transition"]),
        position=Msg("/pathos/diagram/position", (diagram, mv["at"], level, levels, depth)),
        sets=[
            Msg("/pathos/vial/chord", (root, dens, bright, tens)),
            Msg("/pathos/vial/voices", tuple(x for pair in vox for x in pair)),
            Msg("/pathos/chair/heartbeat", (bpm, irr, intensity)),
            Msg("/pathos/chair/drone", (d_freq, d_amp)),
        ],
        numbers={"bpm": bpm, "irregularity": irr, "intensity": intensity, "root_hz": root, "density": dens,
                 "brightness": bright, "tension": round(tens, 4), "voices": vox, "drone": (d_freq, d_amp),
                 "level": level, "levels": levels, "depth": depth, "dur_s": dur_s},
    )


def map_score(score: dict, diagrams: dict[str, Diagram] | None = None) -> Plan:
    """Assumes the score already passed validate.validate_score()."""
    diagrams = diagrams if diagrams is not None else load_diagrams()
    mvs = score["movements"]
    durs = durations(score["length"], [m["span"] for m in mvs])
    mixes = active_mixtures(score)
    return Plan(diagram=score["diagram"], movements=[
        map_movement(i, mv, score["diagram"], mixes[i], durs[i], diagrams) for i, mv in enumerate(mvs)
    ])


def end_sets(last: MappedMovement) -> list[Msg]:
    """§6.5 fade: chair heartbeat intensity 0 and drone amp 0 (keeping bpm/freq so nothing jumps)."""
    bpm, irr = last.numbers["bpm"], last.numbers["irregularity"]
    freq = last.numbers["drone"][0]
    return [Msg("/pathos/chair/heartbeat", (bpm, irr, 0.0)), Msg("/pathos/chair/drone", (freq, 0.0))]
