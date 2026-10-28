"""Contract self-check. Run after every contract edit:  python contract/check_contract.py

- generated schemas are up to date with emotion_vocabulary.json + diagrams.json (build_schemas.py)
- schemas are valid JSON Schema 2020-12
- diagram geometry is consistent (levels contiguous from 0, unique names, active <=> has positions)
- versions agree across files; term count in the .md matches the enum
- every examples/score_*.json and examples/dialogue_*.json validates, including the semantic rules of §3.3
- known-bad scores and turns are rejected
"""
import copy
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_schemas  # noqa: E402

VERSION = build_schemas.VERSION


def load(name):
    return json.loads((HERE / name).read_text())


def semantic_errors(score):
    """Rules from contract §3.3 that JSON Schema can't express. Mirror these in orchestrator/validate.py."""
    errs = []
    phases = [m["phase"] for m in score["movements"]]
    if len(phases) < 2 or phases[1] != "dwell":
        errs.append("dwell must be the second movement")
    if phases[-1] != "resurface":
        errs.append("resurface must be the last movement")
    for key in ("mixture", "destination"):
        names = [e["emotion"] for e in score.get(key, [])]
        if len(names) != len(set(names)):
            errs.append(f"duplicate emotion in {key}")
    if score["mirror_emotion"] not in {e["emotion"] for e in score["mixture"]}:
        errs.append("mirror_emotion must appear in mixture")
    return errs


def main():
    ok = True

    def fail(msg):
        nonlocal ok
        ok = False
        print("FAIL", msg)

    # generated schemas in sync
    built = {"score": build_schemas.score_schema(), "turn": build_schemas.turn_schema(),
             "dialogue": build_schemas.dialogue_schema()}
    schemas = {}
    for name, fresh in built.items():
        on_disk = load(f"{name}.schema.json")
        if on_disk != fresh:
            fail(f"{name}.schema.json is stale: run python contract/build_schemas.py")
        Draft202012Validator.check_schema(on_disk)
        schemas[name] = on_disk

    registry = Registry().with_resources(
        [(s["$id"], Resource.from_contents(s)) for s in schemas.values()]
        + [("turn.schema.json", Resource.from_contents(schemas["turn"]))])
    v_score = Draft202012Validator(schemas["score"], registry=registry)
    v_turn = Draft202012Validator(schemas["turn"], registry=registry)
    v_dialogue = Draft202012Validator(schemas["dialogue"], registry=registry)

    # vocabulary
    vocab = load("emotion_vocabulary.json")
    enum = schemas["score"]["$defs"]["emotion"]["enum"]
    if len(enum) != len(set(enum)):
        fail("duplicate terms in emotion enum")

    # diagram geometry
    geo = load("diagrams.json")
    vocab_files = {d["file"][:-4] for d in vocab["diagrams"]}
    if set(geo["diagrams"]) != vocab_files:
        fail(f"diagrams.json vs emotion_vocabulary.json diagram sets differ: {set(geo['diagrams']) ^ vocab_files}")
    for name, d in geo["diagrams"].items():
        pos = d["positions"]
        if d["active"] != bool(pos):
            fail(f"{name}: active must be true exactly when positions exist")
        if pos:
            names = [p["name"] for p in pos]
            if len(names) != len(set(names)):
                fail(f"{name}: duplicate position names")
            levels = sorted({p["level"] for p in pos})
            if levels != list(range(len(levels))):
                fail(f"{name}: levels must be contiguous from 0, got {levels}")
    active = [k for k, d in geo["diagrams"].items() if d["active"]]

    # versions
    md = (HERE / "interface-contract.md").read_text()
    if f"(v{VERSION})" not in md.splitlines()[0]:
        fail("interface-contract.md title version")
    for name, doc in (("emotion_vocabulary.json", vocab), ("diagrams.json", geo)):
        if doc["contract_version"] != VERSION:
            fail(f"{name} version")
    m = re.search(r"\*\*(\d+) terms\*\*", md)
    if not m or int(m.group(1)) != len(enum):
        fail(f"term count in interface-contract.md should be {len(enum)}")

    # examples
    scores = sorted((HERE / "examples").glob("score_*.json"))
    covered = set()
    for p in scores:
        s = json.loads(p.read_text())
        errs = [e.message for e in v_score.iter_errors(s)] + semantic_errors(s)
        if errs:
            fail(f"{p.name}: {errs}")
        else:
            covered.add(s["diagram"])
            print("ok  ", p.name)
    if set(active) - covered:
        fail(f"no example score for active diagrams {set(active) - covered}")
    for p in sorted((HERE / "examples").glob("dialogue_*.json")):
        d = json.loads(p.read_text())
        errs = [e.message for e in v_dialogue.iter_errors(d)]
        if errs:
            fail(f"{p.name}: {errs}")
        else:
            print("ok  ", p.name)

    # known-bad scores must be rejected
    base = json.loads(scores[0].read_text())
    bad = {}
    b = copy.deepcopy(base); b["mixture"][0]["emotion"] = "sadness"; bad["out-of-vocabulary emotion"] = b
    b = copy.deepcopy(base); b["movements"].reverse(); bad["mirror not first"] = b
    b = copy.deepcopy(base); m_ = b["movements"]; m_[1], m_[2] = m_[2], m_[1]; bad["dwell not second"] = b
    b = copy.deepcopy(base); b["movements"].insert(2, copy.deepcopy(b["movements"][1])); bad["two dwells"] = b
    b = copy.deepcopy(base); b["movements"][-1]["phase"] = "transform"; bad["no resurface"] = b
    b = copy.deepcopy(base); b["movements"][0]["chord"]["color"] = ["p5", "p5"]; bad["repeated interval"] = b
    b = copy.deepcopy(base); b["mixture"].append(copy.deepcopy(b["mixture"][0])); bad["duplicate emotion"] = b
    b = copy.deepcopy(base); b["mirror_emotion"] = "awe"; bad["mirror_emotion not in mixture"] = b
    b = copy.deepcopy(base); b["contract_version"] = "0.2"; bad["old version"] = b
    b = copy.deepcopy(base); b["diagram"] = "desire-indulge"; bad["inactive diagram"] = b
    b = copy.deepcopy(base); b["diagram"] = "habit-build"; b["movements"][0]["at"] = "destiny"; bad["position from another diagram"] = b
    b = copy.deepcopy(base); b["movements"][0]["hug"] = {"breath": "slow", "pressure": "firm"}; bad["hug field"] = b
    b = copy.deepcopy(base); b["movements"][1]["phase"] = "submerge"; bad["submerge phase"] = b
    b = copy.deepcopy(base); del b["length"]; bad["missing length"] = b
    for label, s in bad.items():
        if not (list(v_score.iter_errors(s)) or semantic_errors(s)):
            fail(f"accepted a bad score: {label}")
        else:
            print("ok   rejects", label)

    for label, t in {
        "ask without question": {"action": "ask", "planned_questions": 3, "hypothesis": {"confidence": "low"}},
        "planned 6 questions": {"action": "compose", "planned_questions": 6, "hypothesis": {"confidence": "low"}},
    }.items():
        if not list(v_turn.iter_errors(t)):
            fail(f"accepted a bad turn: {label}")
        else:
            print("ok   rejects turn:", label)

    print("\nALL OK" if ok else "\nERRORS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
