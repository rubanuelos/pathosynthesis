"""Prompt assembly for node 01 (interpretation).

Builds the two system prompts (ask, compose) from system_prompt.md, emotion_framework.json, palette.md and the
contract, and renders a dialogue into the user message. Pure text functions; no network.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

NODE = Path(__file__).resolve().parent
REPO = NODE.parent
CONTRACT = Path(os.environ.get("PATHOS_CONTRACT_DIR", REPO / "contract"))


# ------------------------------------------------------------------ loading
def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def framework() -> dict:
    return _json(NODE / "emotion_framework.json")


@lru_cache(maxsize=None)
def questions() -> dict:
    return _json(NODE / "questions.json")


@lru_cache(maxsize=None)
def schema(name: str) -> dict:
    """name: 'turn', 'score' or 'dialogue'."""
    return _json(CONTRACT / f"{name}.schema.json")


@lru_cache(maxsize=None)
def vocabulary() -> frozenset:
    return frozenset(schema("score")["$defs"]["emotion"]["enum"])


@lru_cache(maxsize=None)
def positions() -> dict:
    """{diagram: {position: level}} for active diagrams, from contract/diagrams.json."""
    geom = _json(CONTRACT / "diagrams.json")["diagrams"]
    return {d: {p["name"]: p["level"] for p in g["positions"]} for d, g in geom.items() if g.get("active")}


@lru_cache(maxsize=None)
def neighbours() -> dict:
    """{diagram: {position: [neighbouring positions]}} from the framework."""
    return {d: {p: v["neighbours"] for p, v in a["positions"].items()} for d, a in framework()["active"].items()}


def lang_block(lang: str | None) -> dict:
    q = questions()
    langs = q["languages"]
    code = (lang or q["default_lang"]).split("-")[0].lower()
    return langs.get(code, langs[q["default_lang"]])


# ------------------------------------------------------------------ rendering the framework
def _star(t: str) -> str:
    return t if t in vocabulary() else t + "*"


def render_active() -> str:
    out = []
    for did, a in framework()["active"].items():
        out.append(f"### {did}\n{a['reading']}\nA visitor is here when they talk about: {a['about']}.")
        out.append("Directions: " + " ".join(f"{k}: {v}" for k, v in a["directions"].items()))
        out.append("Positions (`at`):")
        for name, p in a["positions"].items():
            edge = f"; {' + '.join(p['edge'])}" if p.get("edge") else ""
            out.append(f"- **{name}** (level {p['level']}{edge}): {p['meaning']}. Felt: {p['felt']}. "
                       f"May sound like: {' / '.join(p['cues'])}. Feelings here: {', '.join(p['emotions'])}. "
                       f"Neighbours: {', '.join(p['neighbours'])}.")
        out.append("Trajectories here: " + "; ".join(f"{k}: {v}" for k, v in a["trajectories"].items()) + ".")
        out.append("Kinds of questions that tell positions apart: " + " / ".join(a["probes"]))
        out.append("")
    return "\n".join(out).strip()


def render_choice() -> str:
    c = framework()["diagram_choice"]
    lines = [c["principle"], ""]
    for did in framework()["active"]:
        lines.append(f"- **{did}**: about {c['by_subject'][did]}. Shape in time: {c['by_time_shape'][did]}. "
                     f"They want to: {c['by_intention'][did]}.")
    lines += ["", c["default"]]
    return "\n".join(lines)


def render_vocabulary() -> str:
    return ", ".join(framework()["vocabulary"])


def render_bridges() -> str:
    return "\n".join(f"- {', '.join(b['words'])} → {', '.join(b['toward'])}" + (f" ({b['note']})" if b.get("note") else "")
                     for b in framework()["bridges"]["entries"])


def render_manner() -> str:
    return ", ".join(f"{a}/{b}" for a, b in framework()["manner"])


def render_tension_frames() -> str:
    return "\n".join(f"- {t}" for t in framework()["tension_frames"])


def _nest_chain(rels):
    inner_of = {r["outer"]: r["inner"] for r in rels if r["type"] == "contains"}
    start = [o for o in inner_of if o not in set(inner_of.values())][0]
    chain = [start]
    while chain[-1] in inner_of:
        chain.append(inner_of[chain[-1]])
    return chain


def _render_diagram(d: dict) -> str:
    g, rels, s = d["grammar"], d["relations"], _star
    lines = []
    if g == "tree":
        kids = {}
        for r in rels:
            if r["type"] == "child":
                kids.setdefault(r["parent"], []).append(r["child"])
        lines += [f"{s(p)} -> {', '.join(map(s, cs))}" for p, cs in kids.items()]
        toward = {}
        for r in rels:
            if r["type"] == "orients_toward":
                toward.setdefault(r["to"], []).append(r["from"])
        lines += [f"{', '.join(map(s, fs))} orient toward {s(t)}" for t, fs in toward.items()]
    elif g == "glyph":
        lines += [f"{s(r['term'])}: {r['gloss']}" for r in rels]
    elif g == "lattice":
        for r in rels:
            if r["type"] == "compound":
                lean = f" (leans toward {s(r['leans_toward'])})" if r.get("leans_toward") else ""
                lines.append(f"{s(r['term'])} = {' + '.join(map(s, r['of']))}{lean}")
    elif g == "pentagon":
        lines.append("vertices: " + ", ".join(map(s, d["vertices"])))
        lines.append("; ".join(f"{s(r['term'])} = {s(r['of'][0])} + {s(r['of'][1])}" for r in rels))
    elif g == "arcs":
        lines.append("stages: " + " -> ".join(map(s, d["axis"])))
        lines.append("; ".join(f"{s(r['term'])} ({s(r['from'])}->{s(r['to'])})" for r in rels))
    elif g == "fan":
        lines.append("; ".join(f"{s(r['of'][0])} + {s(r['modifier'])} = {s(r['term'])}" for r in rels))
    elif g == "nest":
        lines.append(" ⊃ ".join(map(s, _nest_chain(rels))))
    body = "\n".join(f"  {l}" for l in lines)
    return f"**{d['id']}** ({g}). {d['gist']}" + (f"\n{body}" if body else "")


def render_background() -> str:
    active = set(framework()["active"])
    return "\n\n".join(_render_diagram(d) for d in framework()["diagrams"] if d["id"] not in active)


def render_palette() -> str:
    text = (NODE / "palette.md").read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->\s*", "", text, flags=re.S)
    text = re.sub(r"^# .*\n", "", text, count=1).strip()
    return re.sub(r"^## ", "### ", text, flags=re.M)


# ------------------------------------------------------------------ system prompts
@lru_cache(maxsize=None)
def system_prompt(kind: str) -> str:
    """kind: 'ask' or 'compose'."""
    raw = (NODE / "system_prompt.md").read_text(encoding="utf-8")
    parts = re.split(r"^# PROMPT: (\w+)\s*$", raw, flags=re.M)
    prompts = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}
    text = prompts[kind]
    fills = {
        "ACTIVE": render_active, "CHOICE": render_choice, "VOCABULARY": render_vocabulary, "BRIDGES": render_bridges,
        "MANNER": render_manner, "TENSION_FRAMES": render_tension_frames, "BACKGROUND": render_background, "PALETTE": render_palette,
    }
    for key, fn in fills.items():
        if "{{" + key + "}}" in text:
            text = text.replace("{{" + key + "}}", fn())
    left = re.findall(r"\{\{\w+\}\}", text)
    if left:
        raise RuntimeError(f"unfilled placeholders in {kind} prompt: {left}")
    return text


# ------------------------------------------------------------------ user messages
def _fmt_hypothesis(h: dict) -> str:
    keys = ["diagram", "at", "mirror_emotion", "trajectory", "length", "confidence", "unknown"]
    return ", ".join(f"{k}={h[k]}" for k in keys if k in h)


def transcript(dialogue: dict) -> str:
    lines = []
    for i, ex in enumerate(dialogue["exchanges"], 1):
        lines.append(f"Q{i}: {ex['question']}")
        if ex["status"] == "ok":
            sec = f", {ex['speech_s']:.1f} s" if isinstance(ex.get("speech_s"), (int, float)) else ""
            lines.append(f"A{i}: {ex['answer']} [ok{sec}]")
        else:
            lines.append(f"A{i}: (no answer) [{ex['status']}]")
        turn = ex.get("turn")
        if turn and turn.get("hypothesis"):
            lines.append(f"   (your hypothesis after A{i}: {_fmt_hypothesis(turn['hypothesis'])}; planned {turn.get('planned_questions')})")
    return "\n".join(lines)


def user_message(kind: str, dialogue: dict) -> str:
    n = len(dialogue["exchanges"])
    head = f"Language detected: {dialogue.get('lang', 'unknown')}. Questions asked so far: {n} (the system allows 2 to 5).\n\n"
    body = "```text\n" + transcript(dialogue) + "\n```\n\n"
    if kind == "ask":
        return head + body + "Decide the next turn and return it with submit_turn."
    return head + body + "Compose the score and return it with submit_score."
