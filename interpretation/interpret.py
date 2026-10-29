"""Node 01 — Interpretation. Contract v0.3 §2.5.

    next_turn(dialogue) -> turn     ask one more question, or say compose     (<= 6 s)
    compose(dialogue)   -> score    the score for this visitor                 (<= 10 s)

Both raise InterpretationError on timeout, provider failure, or output that is still invalid after one retry;
the orchestrator then falls back (fallback probe from questions.json, or a fallback score).

Hard checks (a failure triggers one retry, then InterpretationError):
  turn : turn.schema.json; question <= 25 words, one question; never names a diagram/framework or asks for an
         emotion; does not offer 2+ vocabulary words the visitor never said; hypothesis.at belongs to hypothesis.diagram.
  score: score.schema.json + the contract's semantic rules (dwell second, resurface last, mirror_emotion in mixture,
         no duplicates in mixture/destination).
Soft checks (score_warnings, question_metrics) are composing guidance; they are logged by the eval, never retried.

CLI (test this node alone):
    python -m interpretation.interpret DIALOGUE.json [--turn | --compose] [--provider stub]
    python -m interpretation.interpret --print-prompt ask|compose
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import jsonschema

from . import llm, prompts

TURN_BUDGET_S = float(os.environ.get("PATHOS_TURN_TIMEOUT_S", 6.0))
COMPOSE_BUDGET_S = float(os.environ.get("PATHOS_COMPOSE_TIMEOUT_S", 10.0))
MIN_RETRY_S = {"ask": 2.0, "compose": 4.0}     # only retry if at least this much budget is left
MAX_WORDS = 25
MAX_QUESTIONS = 5

LEAK_PATTERNS = [
    r"diagram\w*", r"framework", r"pentag\w*", r"pentagram\w*", r"nicolae", r"chthonic", r"rina",
    r"emotion\w*", r"emoci\w+", r"émotion\w*", r"emoç\w+",
    r"habit-build", r"fate-engage", r"mystery-engage",
]
LEAK_RE = re.compile(r"\b(" + "|".join(LEAK_PATTERNS) + r")\b", re.I)
WORD_RE = re.compile(r"[\w'’-]+", re.U)


class InterpretationError(Exception):
    """Raised when no valid turn/score could be produced in time. The orchestrator falls back."""


# ------------------------------------------------------------------ helpers
def _validator(name: str):
    sch = prompts.schema(name)
    registry = None
    if name == "dialogue":       # dialogue.schema.json refers to turn.schema.json by relative $ref
        from referencing import Registry, Resource
        turn = prompts.schema("turn")
        registry = Registry().with_resources([
            ("turn.schema.json", Resource.from_contents(turn)),
            (turn.get("$id", "turn.schema.json"), Resource.from_contents(turn)),
        ])
    cls = jsonschema.validators.validator_for(sch)
    return cls(sch, registry=registry) if registry is not None else cls(sch)


_VALIDATORS: dict = {}


def schema_errors(obj: dict, name: str) -> list[str]:
    if name not in _VALIDATORS:
        _VALIDATORS[name] = _validator(name)
    errs = sorted(_VALIDATORS[name].iter_errors(obj), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message[:200]}" for e in errs]


def _words(text: str) -> list[str]:
    return [w.lower().strip("'’-") for w in WORD_RE.findall(text or "")]


def _answers_text(dialogue: dict) -> str:
    return " ".join(e["answer"] for e in dialogue["exchanges"] if e["status"] == "ok").lower()


# ------------------------------------------------------------------ turn checks
def question_metrics(question: str, dialogue: dict) -> dict:
    """Measures used by the hard checks and reported by the eval."""
    said = set(_words(_answers_text(dialogue)))
    qwords = _words(question)
    vocab = prompts.vocabulary()
    pos_names = {p for ps in prompts.positions().values() for p in ps}
    last_ok = next((e["answer"] for e in reversed(dialogue["exchanges"]) if e["status"] == "ok"), "")
    last_words = {w for w in _words(last_ok) if len(w) >= 4}
    return {
        "words": len(qwords),
        "question_marks": question.count("?"),
        "leaks": sorted({m.group(0).lower() for m in LEAK_RE.finditer(question)}),
        "introduced_vocabulary": sorted({w for w in qwords if w in vocab and w not in said}),
        "introduced_positions": sorted({w for w in qwords if w in pos_names and w not in said}),
        "echo": sorted({w for w in qwords if w in last_words}),
    }


def turn_errors(turn: dict, dialogue: dict) -> list[str]:
    errs = schema_errors(turn, "turn")
    if errs:
        return errs
    if turn["action"] == "ask":
        m = question_metrics(turn["question"], dialogue)
        if m["words"] > MAX_WORDS:
            errs.append(f"question has {m['words']} words; max {MAX_WORDS}")
        if m["question_marks"] > 1:
            errs.append("more than one question")
        if m["leaks"]:
            errs.append(f"question names what must stay hidden: {m['leaks']}")
        if len(m["introduced_vocabulary"]) >= 2:
            errs.append(f"question offers feeling words the visitor never said: {m['introduced_vocabulary']}")
        asked = {e["question"].strip().lower() for e in dialogue["exchanges"]}
        if turn["question"].strip().lower() in asked:
            errs.append("question repeats an earlier one")
    h = turn["hypothesis"]
    if "at" in h:
        if "diagram" not in h:
            errs.append("hypothesis.at given without hypothesis.diagram")
        elif h["at"] not in prompts.positions()[h["diagram"]]:
            errs.append(f"hypothesis.at '{h['at']}' is not a position of {h['diagram']}: {sorted(prompts.positions()[h['diagram']])}")
    return errs


def _tidy_turn(turn: dict, dialogue: dict) -> dict:
    """Mechanical fixes that are not semantic choices."""
    n = len(dialogue["exchanges"])
    if isinstance(turn, dict):
        if turn.get("action") == "ask" and n >= MAX_QUESTIONS:
            turn["action"] = "compose"
        if turn.get("action") == "compose":
            turn.pop("question", None)
        if isinstance(turn.get("question"), str):
            turn["question"] = turn["question"].strip().strip('"“”«»').strip()
        pq = turn.get("planned_questions")
        if isinstance(pq, int):
            lo = n + 1 if turn.get("action") == "ask" else n
            turn["planned_questions"] = max(2, min(MAX_QUESTIONS, max(pq, lo)))
    return turn


# ------------------------------------------------------------------ score checks
def score_errors(score: dict) -> list[str]:
    """Schema + the contract's semantic rules (same as check_contract.semantic_errors). Failure = fallback score downstream."""
    errs = schema_errors(score, "score")
    if errs:
        return errs
    phases = [m["phase"] for m in score["movements"]]
    if phases[1] != "dwell":
        errs.append("dwell must be the second movement")
    if phases[-1] != "resurface":
        errs.append("resurface must be the last movement")
    mix = [e["emotion"] for e in score["mixture"]]
    if score["mirror_emotion"] not in mix:
        errs.append("mirror_emotion must appear in mixture")
    if len(mix) != len(set(mix)):
        errs.append("an emotion appears twice in mixture")
    dest = [e["emotion"] for e in score.get("destination", [])]
    if len(dest) != len(set(dest)):
        errs.append("an emotion appears twice in destination")
    return errs


TEMPO = ["very_slow", "slow", "resting", "elevated", "racing"]


def score_warnings(score: dict) -> list[str]:
    """Composing guidance from the prompt. Logged, never enforced."""
    w = []
    mv = score["movements"]
    if score["mixture"][0]["emotion"] != score["mirror_emotion"]:
        w.append("mirror_emotion is not the first mixture entry")
    nb = prompts.neighbours()[score["diagram"]]
    for a, b in zip(mv, mv[1:]):
        if a["at"] != b["at"] and b["at"] not in nb[a["at"]]:
            w.append(f"path jumps {a['at']} -> {b['at']} (not neighbours)")
    mirror, dwell, res = mv[0], mv[1], mv[-1]
    if TEMPO.index(dwell["heartbeat"]["tempo"]) > TEMPO.index(mirror["heartbeat"]["tempo"]):
        w.append("dwell heartbeat faster than mirror")
    limit = "elevated" if score["trajectory"] == "amplify" else "resting"
    if TEMPO.index(res["heartbeat"]["tempo"]) > TEMPO.index(limit):
        w.append(f"resurface tempo {res['heartbeat']['tempo']} above {limit}")
    if res["heartbeat"]["regularity"] == "erratic":
        w.append("resurface erratic")
    if res["transition"] == "cut":
        w.append("resurface arrives with a cut")
    if sum(m["transition"] == "cut" for m in mv) > 1:
        w.append("more than one cut")
    if not set(res["chord"]["color"]) & set(mirror["chord"]["color"]):
        w.append("resurface keeps no interval from the mirror (no trace)")
    if score["trajectory"] == "hold" and score.get("destination"):
        w.append("destination given for hold")
    if score["trajectory"] != "hold" and not score.get("destination"):
        w.append(f"no destination for {score['trajectory']}")
    if score.get("title") and len(score["title"].split()) > 9:
        w.append("title longer than ~8 words")
    return w


# ------------------------------------------------------------------ the loop with a deadline
def _run(kind: str, dialogue: dict, budget: float, meta: dict | None) -> dict:
    t0 = time.monotonic()
    deadline = t0 + budget
    derr = schema_errors(dialogue, "dialogue")
    if derr:
        raise InterpretationError(f"invalid dialogue: {derr[:3]}")
    tool, sch = ("submit_turn", "turn") if kind == "ask" else ("submit_score", "score")
    try:
        provider = llm.get_provider()
        model = llm.model_for(kind, provider.name)
        system = prompts.system_prompt(kind)
        tool_schema = llm.inline_refs(prompts.schema(sch))
    except (llm.LLMError, OSError, KeyError, RuntimeError) as e:
        raise InterpretationError(f"setup failed: {e}") from e
    user = prompts.user_message(kind, dialogue)
    info = {"provider": provider.name, "model": model, "attempts": 0, "errors": []}
    if meta is not None:
        meta.update(info)

    msg, last = user, None
    for attempt in (1, 2):
        remaining = deadline - time.monotonic()
        if remaining < 0.3:
            raise InterpretationError(f"{kind}: out of time after {attempt - 1} attempt(s)")
        info["attempts"] = attempt
        try:
            out = provider.call(kind, system, msg, tool, tool_schema, remaining, context={"dialogue": dialogue})
        except llm.LLMTimeout as e:
            raise InterpretationError(f"{kind}: timeout ({e})") from e
        except llm.LLMError as e:
            info["errors"].append(f"provider: {e}")
            if attempt == 2 or deadline - time.monotonic() < MIN_RETRY_S[kind]:
                raise InterpretationError(f"{kind}: provider error: {e}") from e
            continue
        if kind == "ask":
            out = _tidy_turn(out, dialogue)
            errs = turn_errors(out, dialogue) if isinstance(out, dict) else ["output is not an object"]
        else:
            if isinstance(out, dict):
                out["contract_version"] = "0.3"
            errs = score_errors(out) if isinstance(out, dict) else ["output is not an object"]
        if not errs:
            info["latency_s"] = round(time.monotonic() - t0, 2)
            if meta is not None:
                meta.update(info)
            return out
        info["errors"].append(errs)
        last = out
        if deadline - time.monotonic() < MIN_RETRY_S[kind]:
            break
        msg = (user + "\n\nYour previous answer was rejected:\n- " + "\n- ".join(map(str, errs)) +
               "\n\nPrevious answer:\n" + json.dumps(last, ensure_ascii=False) + "\n\nReturn a corrected one.")
    if meta is not None:
        meta.update(info)
    raise InterpretationError(f"{kind}: invalid output after {info['attempts']} attempt(s): {info['errors'][-1]}")


_last_warm: dict = {}
WARM_EVERY_S = 240          # Anthropic's prompt cache lives ~5 min


def warm(kinds=("ask", "compose"), *, block: bool = False) -> None:
    """Prime the provider's prompt cache so the first next_turn/compose of a session doesn't pay for the long prompt.
    Called internally (compose is warmed while the questions run). The orchestrator may also call it when a session
    starts. Best effort, rate-limited, never raises."""
    import threading
    try:
        provider = llm.get_provider()
    except llm.LLMError:
        return
    if not hasattr(provider, "warm"):
        return
    now = time.monotonic()
    for kind in kinds:
        if now - _last_warm.get(kind, -1e9) < WARM_EVERY_S:
            continue
        _last_warm[kind] = now
        tool, sch = ("submit_turn", "turn") if kind == "ask" else ("submit_score", "score")
        args = (kind, prompts.system_prompt(kind), tool, llm.inline_refs(prompts.schema(sch)))
        t = threading.Thread(target=provider.warm, args=args, daemon=True)
        t.start()
        if block:
            t.join()


def next_turn(dialogue: dict, *, meta: dict | None = None) -> dict:
    """After each answer: ask one more question or compose. Raises InterpretationError (fallback: next probe)."""
    warm(("compose",))
    return _run("ask", dialogue, TURN_BUDGET_S, meta)


def compose(dialogue: dict, *, meta: dict | None = None) -> dict:
    """The score for this dialogue. Raises InterpretationError (fallback: orchestrator's fallback score)."""
    return _run("compose", dialogue, COMPOSE_BUDGET_S, meta)


# ------------------------------------------------------------------ CLI
def _main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m interpretation.interpret", description=__doc__.split("\n\n")[0])
    ap.add_argument("dialogue", nargs="?", help="dialogue JSON (contract/dialogue.schema.json)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--turn", action="store_true", help="force next_turn")
    g.add_argument("--compose", action="store_true", help="force compose")
    ap.add_argument("--provider", help="override PATHOS_LLM (anthropic|openai|ollama|stub)")
    ap.add_argument("--print-prompt", choices=["ask", "compose"], help="print an assembled system prompt and exit")
    a = ap.parse_args(argv)
    if a.provider:
        os.environ["PATHOS_LLM"] = a.provider
    if a.print_prompt:
        text = prompts.system_prompt(a.print_prompt)
        print(text)
        print(f"\n[{len(text)} chars, ~{len(text) // 4} tokens]", file=sys.stderr)
        return 0
    if not a.dialogue:
        ap.error("dialogue file required")
    dialogue = json.loads(open(a.dialogue, encoding="utf-8").read())
    last_turn = (dialogue["exchanges"][-1].get("turn") or {})
    do_compose = a.compose or (not a.turn and (last_turn.get("action") == "compose" or len(dialogue["exchanges"]) >= MAX_QUESTIONS))
    meta: dict = {}
    try:
        out = compose(dialogue, meta=meta) if do_compose else next_turn(dialogue, meta=meta)
    except InterpretationError as e:
        print(json.dumps(meta, ensure_ascii=False), file=sys.stderr)
        print(f"InterpretationError: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    extra = score_warnings(out) if do_compose else question_metrics(out.get("question", ""), dialogue) if out.get("question") else {}
    print(json.dumps({"meta": meta, "checks": extra}, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
