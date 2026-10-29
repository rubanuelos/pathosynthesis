#!/usr/bin/env python3
"""Dialogue eval for node 01: scripted visitors through the real questionnaire loop.

    python -m interpretation.eval.run_eval                     # all dialogues, provider from PATHOS_LLM
    python -m interpretation.eval.run_eval --provider stub     # offline plumbing check (questions are NOT meaningful)
    python -m interpretation.eval.run_eval --only grief --repeat 3

Each file in eval/dialogues/ is a scripted visitor: up to 5 answers given in order to whatever is asked
(null = silence). The harness plays the orchestrator's side of contract §2.2:
  opening question from questions.json -> answer -> next_turn -> ... -> compose
  - silence on the opening: re-ask once, then the visitor leaves (idle)
  - bounds 2..5 questions: compose before 2 -> next fallback probe; 5 answered -> compose
  - next_turn error/timeout -> next fallback probe; compose error -> "FALLBACK SCORE"
  - the model asks but the script has no answers left -> logged as script_exhausted, then compose
Outputs, in eval/runs/<timestamp>_<provider>/:
  <id>.json      full log: every question (source, metrics), turn, hypothesis, score, warnings, latencies
  summary.md     the table and transcripts the team reads to judge "does it feel subliminal?"
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from interpretation import interpret as I  # noqa: E402
from interpretation import prompts  # noqa: E402


def speech_seconds(text: str) -> float:
    return round(len(text.split()) / 2.6 + 0.6, 1)   # ~2.6 words/s spoken, plus onset


def simulate(script: dict) -> dict:
    qb = prompts.lang_block(script["lang"])
    answers = list(script["answers"])
    dialogue = {"contract_version": "0.3", "session_id": f"eval-{script['id']}"[:64], "lang": script["lang"], "exchanges": []}
    log = {"id": script["id"], "lang": script["lang"], "style": script.get("style", ""), "about": script.get("about", ""),
           "expect": script.get("expect", {}), "questions": [], "events": [], "turn_latency_s": [], "outcome": None}
    question, source = qb["opening"], "opening"
    probe_i, ai, reasked = 0, 0, False

    while True:
        if ai >= len(answers):
            log["events"].append({"script_exhausted": True, "unanswered_question": question, "source": source})
            break
        ans = answers[ai]
        ai += 1
        status = "ok" if ans else "silence"
        if not dialogue["exchanges"] and status == "silence":
            if reasked:
                log["outcome"] = "idle (no answer to the opening, twice)"
                return log
            reasked = True
            log["events"].append({"opening_silence": True})
            question, source = qb["reask"], "reask"
            continue
        ex = {"question": question, "answer": ans or "", "status": status}
        if ans:
            ex["speech_s"] = speech_seconds(ans)
        dialogue["exchanges"].append(ex)
        n = len(dialogue["exchanges"])
        log["questions"].append({"n": n, "source": source, "question": question, "answer": ans, "status": status,
                                 "metrics": I.question_metrics(question, {"exchanges": dialogue["exchanges"][:-1] or [{"answer": "", "status": "ok", "question": ""}]})})
        if n >= I.MAX_QUESTIONS:
            log["events"].append({"bound": "5 answered, compose"})
            break
        meta: dict = {}
        try:
            turn = I.next_turn(dialogue, meta=meta)
        except I.InterpretationError as e:
            turn = None
            log["events"].append({"after": n, "next_turn_error": str(e)[:300]})
        if meta.get("latency_s") is not None:
            log["turn_latency_s"].append(meta["latency_s"])
        if meta.get("attempts", 0) > 1:
            log["events"].append({"after": n, "turn_retried": meta.get("errors")})
        if turn:
            ex["turn"] = turn
        if turn and turn["action"] == "ask":
            question, source = turn["question"], "llm"
        elif turn and turn["action"] == "compose" and n >= 2:
            break
        else:
            reason = "error/timeout" if turn is None else "compose before 2"
            question, source = qb["probes"][min(probe_i, len(qb["probes"]) - 1)], f"probe ({reason})"
            probe_i += 1

    log["dialogue"] = dialogue
    meta = {}
    try:
        score = I.compose(dialogue, meta=meta)
        log["score"] = score
        log["warnings"] = I.score_warnings(score)
        log["outcome"] = "score"
    except I.InterpretationError as e:
        log["score"] = None
        log["warnings"] = []
        log["outcome"] = f"FALLBACK SCORE ({str(e)[:200]})"
    log["compose_latency_s"] = meta.get("latency_s")
    log["compose_attempts"] = meta.get("attempts")
    return log


# ------------------------------------------------------------------ reporting
def path_of(score):
    return " → ".join(m["at"] for m in score["movements"]) if score else "—"


def row(log):
    s = log.get("score")
    turns = [q["source"][0] for q in log["questions"]]          # o, r, l, p
    planned = next((x["turn"]["planned_questions"] for x in reversed(log.get("dialogue", {}).get("exchanges", [])) if x.get("turn")), "—")
    exhausted = any(e.get("script_exhausted") for e in log["events"])
    cells = [
        log["id"], log["lang"], f"{len(log['questions'])}{'+' if exhausted else ''} ({''.join(turns)}) / {planned}",
        s["diagram"] if s else "—", path_of(s), s["mirror_emotion"] if s else "—", s["trajectory"] if s else "—",
        s["length"] if s else "—", s["intention_source"] if s else "—",
        str(log["expect"].get("diagram", "")), str(len(log.get("warnings", []))),
        f"{max(log['turn_latency_s']):.1f}" if log["turn_latency_s"] else "—",
        f"{log['compose_latency_s']:.1f}" if log.get("compose_latency_s") is not None else "—",
    ]
    return "| " + " | ".join(cells) + " |"


def transcript_md(log):
    out = [f"### {log['id']}  ·  {log['style']}", f"_{log['about']}_", ""]
    for q in log["questions"]:
        m = q["metrics"]
        flags = []
        if m["echo"]:
            flags.append("echo: " + ", ".join(m["echo"]))
        if m["introduced_vocabulary"]:
            flags.append("introduced: " + ", ".join(m["introduced_vocabulary"]))
        if m["introduced_positions"]:
            flags.append("positions: " + ", ".join(m["introduced_positions"]))
        if m["leaks"]:
            flags.append("LEAK: " + ", ".join(m["leaks"]))
        out.append(f"**Q{q['n']}** [{q['source']}, {m['words']} w{'; ' + '; '.join(flags) if flags else ''}]: {q['question']}  ")
        out.append(f"**A{q['n']}**: {q['answer'] if q['answer'] else '(silence)'}  ")
        ex = log["dialogue"]["exchanges"][q["n"] - 1] if log.get("dialogue") else {}
        h = (ex.get("turn") or {}).get("hypothesis")
        if h:
            out.append(f"<sub>→ {ex['turn']['action']} · planned {ex['turn']['planned_questions']} · "
                       f"{', '.join(f'{k}={v}' for k, v in h.items() if k != 'unknown')}"
                       f"{' · unknown: ' + h['unknown'] if h.get('unknown') else ''}</sub>")
        out.append("")
    for e in log["events"]:
        out.append(f"- event: `{json.dumps(e, ensure_ascii=False)[:300]}`")
    s = log.get("score")
    if s:
        mix = ", ".join(f"{e['emotion']} {e['weight']}" + (f" (“{e['heard']}”)" if e.get("heard") else "") for e in s["mixture"])
        dest = ", ".join(f"{e['emotion']} {e['weight']}" for e in s.get("destination", [])) or "—"
        out += ["", f"**Score:** {s['diagram']} · {path_of(s)} · {s['trajectory']} · {s['length']}  ",
                f"mixture: {mix}  ", f"destination: {dest}  ",
                f"intention ({s['intention_source']}): {s['intention']}  ", f"tension: {s['tension']}  ",
                f"negotiation: {s.get('negotiation', '—')}  ", f"title: *{s.get('title', '—')}*  "]
        mv = " / ".join(f"{m['phase']}@{m['at']} {m['span']} {m['heartbeat']['tempo']}-{m['heartbeat']['regularity']}-{m['heartbeat']['weight']} "
                        f"{m['chord']['register']}[{','.join(m['chord']['color'])}] {m['chord']['density']} {m['chord']['brightness']} {m['transition']}"
                        for m in s["movements"])
        out.append(f"<sub>{mv}</sub>")
    else:
        out.append(f"**Outcome:** {log['outcome']}")
    if log.get("warnings"):
        out.append("warnings: " + "; ".join(log["warnings"]))
    out.append("")
    return "\n".join(out)


def summary_md(logs, provider, model_ask, model_compose):
    qs = [q for l in logs for q in l["questions"] if q["source"] == "llm"]
    lat_t = [x for l in logs for x in l["turn_latency_s"]]
    lat_c = [l["compose_latency_s"] for l in logs if l.get("compose_latency_s") is not None]
    nq = [len(l["questions"]) for l in logs]
    pct = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(p * len(xs)))] if xs else float("nan")
    lines = [
        f"# Interpretation eval — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"Provider **{provider}** (ask: `{model_ask}`, compose: `{model_compose}`) · {len(logs)} visitors"
        + ("  \n**Stub run: questions and scores are templates. This only checks the plumbing.**" if provider == "stub" else ""),
        "",
        "## At a glance",
        "",
        f"- Questions per visitor: {statistics.mean(nq):.1f} on average (min {min(nq)}, max {max(nq)})",
        f"- Generated questions: {len(qs)}; with an echo of the visitor's last answer: {sum(1 for q in qs if q['metrics']['echo'])}; "
        f"introducing vocabulary words: {sum(1 for q in qs if q['metrics']['introduced_vocabulary'])}; "
        f"introducing position names: {sum(1 for q in qs if q['metrics']['introduced_positions'])}; leaks: {sum(1 for q in qs if q['metrics']['leaks'])}",
        f"- Fallback probes used: {sum(1 for l in logs for q in l['questions'] if q['source'].startswith('probe'))}; "
        f"fallback scores: {sum(1 for l in logs if l['outcome'] != 'score' and not str(l['outcome']).startswith('idle'))}",
        f"- next_turn latency p50 {pct(lat_t, .5):.1f} s, p95 {pct(lat_t, .95):.1f} s (budget {I.TURN_BUDGET_S:.0f} s) · "
        f"compose p50 {pct(lat_c, .5):.1f} s, p95 {pct(lat_c, .95):.1f} s (budget {I.COMPOSE_BUDGET_S:.0f} s)",
        "",
        "Questions column: count (sources: o opening, r re-ask, l generated, p fallback probe) / final planned_questions. "
        "`+` = the model wanted another question but the script had no answer left.",
        "",
        "| visitor | lang | questions | diagram | path | mirror | trajectory | length | intention | expected diagram | warn | turn s max | compose s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [row(l) for l in logs]
    lines += ["", "## Transcripts", ""]
    lines += [transcript_md(l) for l in logs]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--provider", help="override PATHOS_LLM")
    ap.add_argument("--only", help="substring filter on dialogue ids")
    ap.add_argument("--repeat", type=int, default=1, help="run each dialogue N times (variance)")
    ap.add_argument("--out", help="output folder (default eval/runs/<timestamp>_<provider>)")
    a = ap.parse_args(argv)
    if a.provider:
        os.environ["PATHOS_LLM"] = a.provider
    provider = os.environ.get("PATHOS_LLM", "anthropic")
    from interpretation import llm
    try:
        m_ask, m_comp = llm.model_for("ask", provider), llm.model_for("compose", provider)
    except llm.LLMError as e:
        sys.exit(str(e))

    files = sorted((HERE / "dialogues").glob("*.json"))
    scripts = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    if a.only:
        scripts = [s for s in scripts if a.only in s["id"]]
    out = Path(a.out) if a.out else HERE / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}_{provider}"
    out.mkdir(parents=True, exist_ok=True)

    logs = []
    for s in scripts:
        for r in range(a.repeat):
            t0 = time.monotonic()
            log = simulate(s)
            if a.repeat > 1:
                log["id"] = f"{s['id']}#{r + 1}"
            logs.append(log)
            (out / f"{log['id'].replace('#', '_')}.json").write_text(json.dumps(log, indent=2, ensure_ascii=False))
            sc = log.get("score") or {}
            print(f"{log['id']:<30} q={len(log['questions'])} {sc.get('diagram', '—'):<15} {path_of(sc) if sc else log['outcome']:<40} "
                  f"{sc.get('trajectory', ''):<10} {time.monotonic() - t0:5.1f}s")
    (out / "summary.md").write_text(summary_md(logs, provider, m_ask, m_comp), encoding="utf-8")
    print(f"\nwrote {out / 'summary.md'}")


if __name__ == "__main__":
    main()
