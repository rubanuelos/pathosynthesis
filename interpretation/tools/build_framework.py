#!/usr/bin/env python3
"""Build interpretation/emotion_framework.json and its two review docs.

    python interpretation/tools/build_framework.py

Reads (contract, never edited here):
  contract/score.schema.json   -> the emotion vocabulary ($defs.emotion.enum, 123 terms)
  contract/diagrams.json       -> active diagrams, their positions and levels
Reads (this node):
  interpretation/tools/framework_diagrams.py -> encodings of all 26 diagrams
Writes:
  interpretation/emotion_framework.json
  interpretation/docs/active_diagrams.md     (how the three active diagrams are read: for Rubén to correct)
  interpretation/docs/framework_readings.md  (all 26 diagrams)

Fails loudly if any emotion named here is not in the contract vocabulary, or if the active positions
disagree with contract/diagrams.json.
"""
import json
import pathlib
import sys
from collections import OrderedDict, defaultdict

HERE = pathlib.Path(__file__).resolve().parent
NODE = HERE.parent                      # interpretation/
REPO = NODE.parent
CONTRACT = REPO / "contract"
sys.path.insert(0, str(HERE))
from framework_diagrams import D  # noqa: E402

VOCAB = json.loads((CONTRACT / "score.schema.json").read_text())["$defs"]["emotion"]["enum"]
VOCAB_SET = set(VOCAB)
GEOM = json.loads((CONTRACT / "diagrams.json").read_text())["diagrams"]
ACTIVE_IDS = sorted(k for k, v in GEOM.items() if v.get("active"))


def need_vocab(terms, where):
    bad = [t for t in terms if t not in VOCAB_SET]
    assert not bad, f"{where}: not in contract vocabulary: {bad}"


# ============================================================== active diagrams
# What each position means, how a visitor's language points to it, and what moving in each direction means.
# `emotions` = vocabulary terms that tend to live at a position (used for mixtures and mirror_emotion).
# `cues` = phrases a visitor might say (any language; English examples). Never spoken back as labels.

ACTIVE = OrderedDict()

ACTIVE["habit-build"] = dict(
    drawn="Five circles nested inside each other, all touching at one point on the left: intention (smallest), action, behavior, habit, nature (largest).",
    reading=("Repetition and time. An intention, once done, is an action; actions repeated in a kind of situation become behavior; "
             "behavior repeated without deciding becomes habit; habit kept long enough becomes nature, 'who I am'. "
             "Every ring touches the same point on the left: every nature was once an intention, and the way back to that point is always open. "
             "Inner rings are small, recent, chosen and fragile; outer rings are large, old, automatic and heavy."),
    about="what the visitor does, keeps doing, can't stop doing, wants to start, or is: patterns, routines, the body acting on its own, identity",
    directions={
        "outward": "sediment: something repeated until it becomes who you are. Thickening, consolidating, automatic. Can feel like strength (dignity, competence, stabilization) or like a trap (compulsion, spiral).",
        "inward": "return: an automatism unpicked back to the moment it was a choice. Loosening, lighter, more fragile and more free (possibility, choice, aspiration).",
    },
    positions=OrderedDict(
        intention=dict(meaning="what you mean to do and have not done yet; a wish with a direction",
                       felt="small, light, unsure, open",
                       cues=["I want to", "I'm going to", "I promised myself", "I keep meaning to", "I wish I could start"],
                       emotions=["aspiration", "wishing", "hope", "ambition", "possibility", "choice", "commitment", "uncertainty"]),
        action=dict(meaning="one act, now or just done; a threshold crossed once",
                    felt="sharp, charged, exposed, alive",
                    cues=["I finally", "I did it", "I said it", "today I", "I'm about to"],
                    emotions=["urgency", "excitement", "risk", "gamble", "refusal", "transgression", "fear"]),
        behavior=dict(meaning="how you act in a kind of situation or with certain people; the act with a context",
                      felt="social, watchful, shaped by others",
                      cues=["when I'm with", "at work I", "whenever someone", "I tend to", "around her I"],
                      emotions=["restraint", "submission", "insecurity", "competence", "clumsiness", "vigilance", "dependency"]),
        habit=dict(meaning="what you do again without deciding; the loop",
                   felt="familiar, worn, comforting or trapping",
                   cues=["again", "every time", "I keep", "I can't stop", "I always end up", "every night"],
                   emotions=["compulsion", "urge", "spiral", "obsession", "repression", "comfort", "safety", "stabilization"]),
        nature=dict(meaning="what you are; old, given, felt as temperament or identity",
                    felt="vast, heavy, settled, inevitable",
                    cues=["that's who I am", "I've always been", "it's in my family", "my whole life", "it's how I'm made"],
                    emotions=["necessity", "dignity", "fate", "suffering", "peace", "serenity", "fragility"]),
    ),
    trajectories=dict(
        hold="stay on the ring where they are; let it be accompanied",
        amplify="outward: let it become more fully theirs",
        dissolve="inward toward intention: the automatism loosens back into a choice",
        release="toward action: one act discharges what the ring holds",
        transmute="from habit or nature inward to intention: the same energy becomes a choice again",
    ),
    probes=["What does the body do, unasked?", "Is it new, or does it return?", "What comes just before it?"],
)

ACTIVE["fate-engage"] = dict(
    drawn="Two curves rise from a wide base and bend inward until they meet at a black dot. A straight arrow leaves the dot upward. 'fate' is written in the open space between the curves, 'destiny' on the arrow. The dot is unnamed ('point' in the contract).",
    reading=("Fate is the wide field of things that happen to you: forces converging from both sides, not chosen. "
             "As they converge the space narrows to a single point, the moment when everything meets and something has to give: "
             "a crossroads, a decision, a now. Destiny is the one direction that leaves that point. "
             "Bottom to top: undergoing, converging, directing; many becoming one."),
    about="what happened or is happening to the visitor, decisions, the future, control and its absence, chance, timing, beginnings and endings",
    directions={
        "upward": "from what happens to you toward a direction you take: narrowing and gathering, pressure at the point, then release along the arrow.",
        "downward": "from a direction back into the field: letting go of control, widening, handing it back to what is larger than you.",
    },
    positions=OrderedDict(
        fate=dict(meaning="what happens to you: circumstance, chance, other people's choices, the body, history; wide and not yours",
                  felt="wide, surrounded, carried, sometimes crushing, sometimes spacious",
                  cues=["it happened", "I had no choice", "out of my hands", "they decided", "it's meant to be", "nothing I can do"],
                  emotions=["fate", "necessity", "chance", "submission", "coercion", "vulnerability", "uncertainty", "threat"]),
        point=dict(meaning="convergence: the narrowest place; a decision, a deadline, a crossroads; pressure",
                   felt="tight, pressed, held breath, everything at once",
                   cues=["I have to decide", "everything at once", "next week", "now or never", "I'm torn", "I can't choose"],
                   emotions=["choice", "gamble", "risk", "urgency", "anxiety", "uncertainty", "opportunity", "threat", "excitement"]),
        destiny=dict(meaning="a direction taken or found; being carried forward; purpose",
                     felt="clear, upward, thin and bright, committed",
                     cues=["I know where I'm going", "I'm meant to", "it all makes sense now", "this is my path", "I'm ready"],
                     emotions=["destiny", "commitment", "aspiration", "ambition", "hope", "synchronicity", "opportunity", "faith"]),
    ),
    trajectories=dict(
        hold="stay where they are",
        amplify="upward: the forces gather into a direction",
        dissolve="downward into fate: widen, out of your hands, relief from deciding",
        release="through the point: pressure, then the arrow (point to destiny)",
        transmute="fate to destiny: what happened to you becomes the direction you take",
    ),
    probes=["Did it come to you, or did you go to it?", "Whose hand is on it?", "Which way is it leaning?"],
)

MYST_VERTICES = ["mystery", "desire", "vulnerability", "hope", "absence"]
ACTIVE["mystery-engage"] = dict(
    drawn="A pentagon with a five-pointed star inside it. Vertices: MYSTERY (top), DESIRE, VULNERABILITY, HOPE, ABSENCE. All ten lines are labelled: the five sides VOID, ALLURE, NEED, DISAPPOINTMENT, PATIENCE; the five star lines LONGING, FAITH, AWE, LOSS, EXPECTATION.",
    reading=("Each line is the mixture of its two ends. Vertices are single ingredients; sides mix two neighbours; "
             "star lines mix two distant ingredients and cross through the middle of the figure. "
             "So the radial axis is a scale of mixture: outside is one clear feeling, the centre is two far-apart feelings held at once. "
             "The contract's levels follow this (star lines 0, sides 1, vertices 2). "
             "Two positions that share an ingredient are neighbours: moving between them keeps one feeling and changes the other."),
    about="someone or something missing or wanted, waiting, grief, love, not knowing, wonder, trust, being exposed: feeling more than doing or deciding",
    directions={
        "inward": "toward the centre (star lines): more mixed, deeper, two far things held at once.",
        "outward": "toward a vertex: untangling into one ingredient; clarity, naming.",
        "along": "between positions that share a vertex: one ingredient stays, the other changes (loss to patience keeps absence; disappointment to patience keeps hope). This is how this diagram transmutes.",
    },
    positions=OrderedDict(
        longing=dict(meaning="absence + desire: wanting what is not here", felt="stretched across a distance",
                     cues=["I miss", "I wish she were here", "so far away"], emotions=["longing", "absence", "desire", "lack", "wishing", "attachment"]),
        faith=dict(meaning="mystery + hope: trusting what you cannot see", felt="quiet, open, upheld",
                   cues=["I trust", "something bigger", "it will be ok, I can't say how"], emotions=["faith", "mystery", "hope", "sacredness", "peace"]),
        awe=dict(meaning="mystery + vulnerability: exposed to something too large", felt="small, open, trembling, wide",
                 cues=["so big", "I felt tiny", "it took my breath away"], emotions=["awe", "mystery", "vulnerability", "revelation", "transcendence"]),
        loss=dict(meaning="absence + vulnerability: exposed where something was", felt="raw, hollow, heavy",
                  cues=["she died", "since he left", "I lost", "it's gone"], emotions=["loss", "absence", "vulnerability", "suffering", "longing"]),
        expectation=dict(meaning="desire + hope: wanting something that may come", felt="leaning forward, tense, bright",
                         cues=["I'm waiting to hear", "tomorrow I find out", "I want it to happen"], emotions=["expectation", "desire", "hope", "anxiety", "excitement"]),
        void=dict(meaning="mystery + absence: an emptiness you cannot read", felt="blank, flat, dark, still",
                  cues=["empty", "nothing", "blank", "I don't feel anything"], emotions=["void", "mystery", "absence", "dissipation", "lack"]),
        allure=dict(meaning="mystery + desire: drawn toward what you cannot see", felt="pulled, curious, warm",
                    cues=["drawn to", "I can't stop thinking about", "curious"], emotions=["allure", "mystery", "desire", "attraction", "infatuation"]),
        need=dict(meaning="desire + vulnerability: wanting while exposed", felt="reaching, unguarded",
                  cues=["I need", "I can't do this alone"], emotions=["need", "desire", "vulnerability", "dependency", "lack"]),
        disappointment=dict(meaning="vulnerability + hope: hope that was hurt", felt="deflated, tender",
                            cues=["I hoped", "it didn't happen", "let down"], emotions=["disappointment", "vulnerability", "hope", "loss"]),
        patience=dict(meaning="hope + absence: hoping through an absence; waiting", felt="slow, steady, long",
                      cues=["waiting", "one day", "I can wait"], emotions=["patience", "hope", "absence", "faith", "serenity"]),
        mystery=dict(meaning="the unknown; what cannot be grasped", felt="dim, vast, unresolved",
                     cues=["I don't know what it is", "strange", "I can't name it"], emotions=["mystery", "uncertainty", "ambiguity", "illegibility"]),
        desire=dict(meaning="wanting", felt="warm, reaching, alive",
                    cues=["I want", "I crave"], emotions=["desire", "appetite", "attraction", "urge"]),
        vulnerability=dict(meaning="being exposed, unguarded", felt="raw, thin-skinned, open",
                           cues=["exposed", "raw", "fragile", "naked"], emotions=["vulnerability", "fragility", "insecurity", "fear"]),
        hope=dict(meaning="leaning toward something good that is not here yet", felt="light, upward, tentative",
                  cues=["maybe", "I hope", "it could be"], emotions=["hope", "aspiration", "possibility", "opportunity"]),
        absence=dict(meaning="something or someone not here", felt="hollow, quiet, a gap",
                     cues=["missing", "not here", "gone quiet"], emotions=["absence", "lack", "loss", "longing"]),
    ),
    trajectories=dict(
        hold="stay on the line where they are",
        amplify="inward: let both ingredients be felt at once (side to a star line that shares a vertex)",
        dissolve="outward: untangle into one ingredient, usually toward hope or patience when they want ease",
        release="from a star line outward to a side, then a vertex: the knot opens",
        transmute="along a shared vertex: keep one ingredient, change the other",
    ),
    probes=["Who is missing from this?", "How long is the wait?", "What would the hands reach for?"],
)

DIAGRAM_CHOICE = OrderedDict(
    principle="Choose by what the feeling is about and the shape it has in time, not by its name. The same word (fear, hope) can live in any of the three.",
    by_subject={
        "habit-build": "doing, repeating, being: 'I keep', 'I always', 'I want to stop/start', 'that's who I am', the body acting on its own, how they do things",
        "fate-engage": "happening and deciding: an event, a circumstance, a choice to make, the future, control, chance, 'why me', 'what now'",
        "mystery-engage": "missing, wanting, waiting, not knowing, wonder, grief, love: a feeling with no task attached",
    },
    by_time_shape={
        "habit-build": "a loop or a long history",
        "fate-engage": "an event or a deadline",
        "mystery-engage": "a gap or a wait",
    },
    by_intention={
        "habit-build": "change what I do; stop; start; be different",
        "fate-engage": "decide; accept; let it be; move on; take control",
        "mystery-engage": "feel it; bear it; understand it; be with it; hope",
    },
    default="If still undecided after the last answer: mystery-engage for a feeling without a story, fate-engage when there is a story, habit-build when there is a 'how'.",
)

# Manner vocabulary (boundary-setting.png): how things are done. For questions and palette, never mixture.
MANNER = [("clumsy", "graceful"), ("strained", "easy"), ("hesitant", "decisive"),
          ("rigid", "flexible"), ("insincere", "genuine"), ("reckless", "considerate")]

# Relational frames the vocabulary excludes but the tension field may use (contract emotion_vocabulary.json notes).
TENSION_FRAMES = [
    "my will / the will of the world (will-project): pushing outward inside something larger that holds you",
    "it's your choice / it's not your choice (reality-influence): a feeling arrives unchosen, what you do with it is chosen",
]

# ============================================================== bridges (team proposal, not Nicolae's)
BRIDGES = [
    ("sad, sadness", ["loss", "disappointment", "absence"], ""),
    ("grief, mourning", ["loss", "longing", "absence"], "add devotion or care when the loss is of a person"),
    ("relief", ["safety", "comfort"], "often keeps a trace of what it ends: vigilance at low weight"),
    ("angry, anger, rage, furious", ["violation", "refusal", "justice", "urgency"], "choose by what the anger wants: justice (consequences), refusal (a no), destruction (to break); hot rage adds urgency"),
    ("frustrated", ["lack", "urge", "disappointment"], ""),
    ("ashamed, embarrassed, humiliated", ["insecurity", "fragility", "vulnerability"], "insecurity = recognition + fragility: being seen while fragile"),
    ("guilty, guilt", ["justice", "mercy"], "guilt waits for justice or hopes for mercy"),
    ("lonely", ["lack", "longing", "need"], "belonging is what is missing"),
    ("tired, exhausted, burnt out", ["dissipation", "need"], "maintenance with no surplus"),
    ("numb, empty", ["void", "absence"], ""),
    ("overwhelmed", ["hypervigilance", "urgency", "spiral"], "surplus with nowhere to go"),
    ("stressed", ["anxiety", "urgency", "vigilance"], ""),
    ("calm, at peace", ["serenity", "peace", "comfort"], ""),
    ("happy, joyful", ["play", "excitement", "harmony"], ""),
    ("love, in love", ["devotion", "intimacy", "attachment", "romance", "care"], "pick 2-3"),
    ("jealous", ["attachment", "insecurity", "possession"], ""),
    ("envious", ["lack", "desire", "admiration"], ""),
    ("confused, lost", ["ambiguity", "uncertainty", "illegibility"], ""),
    ("nostalgic", ["longing", "absence", "comfort"], ""),
    ("bored", ["lack", "void"], ""),
    ("grateful", ["care", "communion"], ""),
    ("proud", ["glory", "dignity", "admiration"], ""),
    ("nervous", ["anxiety", "excitement"], "the uncertainty fork, both sides at once"),
    ("restless", ["urge", "lack", "urgency"], ""),
    ("hopeless", ["disappointment", "void", "loss"], ""),
    ("scared, afraid", ["fear", "vulnerability"], ""),
    ("amazed, in awe", ["awe", "mystery", "revelation"], ""),
]
GAPS = ["anger", "sadness", "joy", "shame", "guilt", "disgust", "surprise", "relief", "tiredness", "boredom", "pride", "gratitude", "contempt"]

DECISIONS = [
    {"date": "2026-10-26", "by": "Rubén", "decision": "Attraction glyphs: black dot = desirer, white circle = desired."},
    {"date": "2026-10-26", "by": "Rubén", "decision": "Fandom and following share a recipe; fandom leans toward idealization, following toward submission."},
    {"date": "2026-10-26", "by": "Rubén", "decision": "Play diamond: more grace and more clumsiness = play; less of both = competence."},
    {"date": "2026-10-26", "by": "Rubén", "decision": "Bridges approved in principle as an interpretive tool."},
    {"date": "2026-10-28", "by": "contract v0.3", "decision": "Emotion vocabulary = the contract's frozen 123-term enum (emotion_vocabulary.json). The draft affect/stance/frame/manner kinds are retired; nodes now say in_vocabulary true/false."},
    {"date": "2026-10-28", "by": "contract v0.3", "decision": "Active diagrams: habit-build, fate-engage, mystery-engage. Diagram ids are file slugs."},
]

OPEN_QUESTIONS = [
    "Active diagram readings (docs/active_diagrams.md): positions, directions, trajectory tendencies, diagram choice. Everything downstream depends on these.",
    "mystery-engage: are the star lines the 'most mixed' centre (as the contract levels imply), and does amplify mean inward?",
    "fate-engage: is the wide base of fate felt as oppressive, spacious, or both? It decides what dissolve (downward) means.",
    "habit-build: does the shared tangent point on the left mean 'the way back to intention is always open'?",
    "Same word in several diagrams = one node (seduction, meaning, void, longing...). OK?",
    "Commitment and indirect-action lattices: line tracing still unchecked.",
]

# ============================================================== build
def adjacency(did, positions):
    """Neighbours a movement may step to. habit/fate: |level difference| <= 1. mystery: share an ingredient (vertex)."""
    out = {}
    if did == "mystery-engage":
        ingr = {p["name"]: set(p.get("edge") or [p["name"]]) for p in positions}
        for a in ingr:
            out[a] = [b for b in ingr if b != a and ingr[a] & ingr[b]]
    else:
        lvl = {p["name"]: p["level"] for p in positions}
        for a in lvl:
            out[a] = [b for b in lvl if b != a and abs(lvl[a] - lvl[b]) <= 1]
    return out


assert ACTIVE_IDS == sorted(ACTIVE), f"active diagrams differ: contract {ACTIVE_IDS} vs framework {sorted(ACTIVE)}"
active_out = OrderedDict()
for did, a in ACTIVE.items():
    geom = GEOM[did]
    names = [p["name"] for p in geom["positions"]]
    assert sorted(names) == sorted(a["positions"]), f"{did}: positions differ from contract/diagrams.json"
    levels = max(p["level"] for p in geom["positions"]) + 1
    adj = adjacency(did, geom["positions"])
    pos_out = OrderedDict()
    for p in geom["positions"]:
        mine = a["positions"][p["name"]]
        need_vocab(mine["emotions"], f"{did}.{p['name']}")
        entry = OrderedDict(level=p["level"])
        if p.get("edge"):
            entry["edge"] = p["edge"]
        meaning = mine["meaning"]
        if p.get("edge") and meaning.startswith(" + ".join(p["edge"]) + ": "):
            meaning = meaning[len(" + ".join(p["edge"]) + ": "):]       # the edge is shown separately
        entry.update(meaning=meaning, felt=mine["felt"], cues=mine["cues"], emotions=mine["emotions"], neighbours=adj[p["name"]])
        pos_out[p["name"]] = entry
    active_out[did] = OrderedDict(
        file=geom["file"], axis=geom["axis"], levels=levels, drawn=a["drawn"], reading=a["reading"], about=a["about"],
        directions=a["directions"], positions=pos_out, trajectories=a["trajectories"], probes=a["probes"])

# nodes: every word in every diagram, flagged by vocabulary membership
TERM_KEYS_SINGLE = ("parent", "child", "from", "to", "term", "outer", "inner", "x", "y", "modifier", "on")
TERM_KEYS_LIST = ("of", "poles", "sets", "members")


def terms_of(rel):
    out = [rel[k] for k in TERM_KEYS_SINGLE if isinstance(rel.get(k), str)]
    for k in TERM_KEYS_LIST:
        out += list(rel.get(k) or [])
    return out


node_diagrams = defaultdict(list)
for d in D:
    terms = set()
    for r in d["relations"]:
        terms.update(terms_of(r))
    terms.update(d.get("vertices", []))
    terms.update(d.get("axis", []))
    for t in sorted(terms):
        node_diagrams[t].append(d["id"])
NOTES = {
    "longing": "Three diagrams agree: lack + desire, absence + desire, the lack -> attraction stretch.",
    "temptation": "The hinge between appetite and violation.",
    "compulsion": "Felt quality only. Never a label about the visitor.",
    "obsession": "Felt quality only. Never a label about the visitor.",
    "void": "Absence + mystery (mystery-engage); level 0 of power (power-develop).",
}
nodes = OrderedDict()
for t in sorted(node_diagrams):
    n = OrderedDict(in_vocabulary=t in VOCAB_SET, diagrams=node_diagrams[t])
    if t in NOTES:
        n["note"] = NOTES[t]
    nodes[t] = n
missing_from_diagrams = sorted(VOCAB_SET - set(nodes))
assert not missing_from_diagrams, f"vocabulary terms not found in any encoded diagram: {missing_from_diagrams}"

bridges = []
for words, toward, note in BRIDGES:
    need_vocab(toward, f"bridge {words}")
    b = OrderedDict(words=[w.strip() for w in words.split(",")], toward=toward)
    if note:
        b["note"] = note
    bridges.append(b)

GRAMMARS = OrderedDict([
    ("tree", "Branching. Solid line = splits into / is a kind of. Dashed arrow = orients toward."),
    ("glyph", "Black dot (desirer) -> white circle (desired). Dashed ring = boundary, faint = veiled or degraded, double arrow = reciprocal pull."),
    ("lattice", "Top concept -> middle modes. Each bottom form is a recipe of the modes wired to it; same recipe can differ by lean."),
    ("pentagon", "Five base feelings at the vertices; each of the ten lines is named for the blend of its two ends."),
    ("arcs", "Stages on a baseline; each named region spans a stretch between stages."),
    ("fan", "Base + modifier = compound."),
    ("nest", "Containment. Shared tangent = common ground."),
    ("ladder", "Ascending (or descending) sequence."),
    ("quadrant", "Two axes, four named cells."),
    ("venn", "Two sets; the overlap matters."),
    ("signed", "Direction of change: + more of both, - less of both."),
    ("vector", "Converging forces and the direction that leaves them."),
    ("flow", "Arrows of energy or excess; solid = directed, dashed = drift."),
    ("axes", "Bipolar scales."),
])

DIAG_KEYS = ["id", "alias", "file", "title", "grammar", "confidence", "drawn", "reading", "gist", "questions"]
framework = OrderedDict(
    framework_version="0.3-draft",
    contract_version="0.3",
    status="DRAFT: active-diagram readings awaiting Rubén's correction (docs/active_diagrams.md)",
    source="Rina Nicolae (@chthonic__youth), 26 diagrams in chthonic-youth-diagrams/. Encoding by the Pathosynthesis team. Generated by interpretation/tools/build_framework.py; edit there.",
    how_to_use=("interpret.py renders this file into both system prompts. Emotions anywhere in this file are contract vocabulary terms "
                "(contract/score.schema.json $defs.emotion). Position names are the diagrams' own words and are never spoken to visitors."),
    vocabulary=VOCAB,
    active=active_out,
    diagram_choice=DIAGRAM_CHOICE,
    manner=[list(p) for p in MANNER],
    tension_frames=TENSION_FRAMES,
    bridges=OrderedDict(status="Team proposal, not Nicolae's. Approved in principle by Rubén 2026-10-26.", gaps_in_framework=GAPS, entries=bridges),
    grammars=GRAMMARS,
    nodes=nodes,
    diagrams=[OrderedDict((k, d[k]) for k in DIAG_KEYS + [x for x in ("resolved", "vertices", "axis", "isomorphic_with", "glosses") if x in d] + ["relations"]) for d in D],
    decisions=DECISIONS,
    open_questions=OPEN_QUESTIONS,
)
(NODE / "emotion_framework.json").write_text(json.dumps(framework, indent=2, ensure_ascii=False) + "\n")

# ============================================================== docs/active_diagrams.md
md = ["# The three active diagrams: how interpretation reads them", "",
      "Draft for correction. These readings decide which diagram a visitor lands in, where the piece starts, and which way it moves. "
      "Positions and levels are the contract's (`contract/diagrams.json`); meanings, cues, directions and trajectory tendencies are interpretation's. "
      "Correct anything here and the builder regenerates `emotion_framework.json` and both prompts.", ""]
for did, a in active_out.items():
    md += [f"## {did}", "", f"**Drawn:** {a['drawn']}", "", f"**Reading:** {a['reading']}", "",
           f"**A visitor lands here when they talk about:** {a['about']}.", "", "**Directions**", ""]
    md += [f"- **{k}**: {v}" for k, v in a["directions"].items()]
    md += ["", "| position | level | meaning | felt | visitor might say | emotions that live here | neighbours |", "|---|---|---|---|---|---|---|"]
    for name, p in a["positions"].items():
        lvl = f"{p['level']}" + (f" ({' + '.join(p['edge'])})" if p.get("edge") else "")
        md.append(f"| **{name}** | {lvl} | {p['meaning']} | {p['felt']} | {'; '.join(p['cues'])} | {', '.join(p['emotions'])} | {', '.join(p['neighbours'])} |")
    md += ["", "**Trajectories in this diagram**", ""]
    md += [f"- `{k}`: {v}" for k, v in a["trajectories"].items()]
    md += ["", "**Questions that tell positions apart** (examples of the kind and the voice; the live questions are generated from the visitor's own words)", ""]
    md += [f"- {q}" for q in a["probes"]]
    md.append("")
md += ["## Choosing a diagram", "", DIAGRAM_CHOICE["principle"], "", "| | habit-build | fate-engage | mystery-engage |", "|---|---|---|---|"]
for key, label in [("by_subject", "about"), ("by_time_shape", "shape in time"), ("by_intention", "what they want")]:
    row = DIAGRAM_CHOICE[key]
    md.append(f"| {label} | {row['habit-build']} | {row['fate-engage']} | {row['mystery-engage']} |")
md += ["", f"Default: {DIAGRAM_CHOICE['default']}", "", "## Open questions", ""] + [f"- {q}" for q in OPEN_QUESTIONS[:4]]
(NODE / "docs").mkdir(exist_ok=True)
(NODE / "docs" / "active_diagrams.md").write_text("\n".join(md) + "\n")

# ============================================================== docs/framework_readings.md (all 26)
md = ["# Emotion framework: how each diagram is read", "",
      f"Review document for `emotion_framework.json` ({framework['framework_version']}). The three active diagrams are covered in depth in `active_diagrams.md`. "
      "**Drawn** is what is literally on the page; **Reading** is the interpretation; **Check** is where it is unsure. "
      "Words marked with * are not in the contract vocabulary (they can describe the diagram, never a visitor's mixture).", ""]
md += ["## Per diagram", ""]
for d in D:
    star = lambda t: t if t in VOCAB_SET else t + "*"
    words = sorted({t for r in d["relations"] for t in terms_of(r)} | set(d.get("vertices", [])) | set(d.get("axis", [])))
    md.append(f"### {d['image']:02d} · {d['id']}" + ("  (active)" if d["id"] in ACTIVE_IDS else ""))
    md.append(f"{d['grammar']} · confidence: **{d['confidence']}**\n")
    md.append(f"**Drawn:** {d['drawn']}\n")
    md.append(f"**Reading:** {d['reading']}\n")
    md.append("**Words:** " + ", ".join(star(t) for t in words) + "\n")
    if d.get("resolved"):
        md.append("**Resolved:** " + " ".join(d["resolved"]) + "\n")
    if d["questions"]:
        md.append("**Check:** " + " ".join(d["questions"]) + "\n")
md += ["## Bridges (team proposal)", "", "Common words with no node translate into mixtures of vocabulary terms.", ""]
md += [f"- {', '.join(b['words'])} → {', '.join(b['toward'])}" + (f" — {b['note']}" if b.get("note") else "") for b in bridges]
md += ["", "## Decisions", ""] + [f"- {x['date']} ({x['by']}): {x['decision']}" for x in DECISIONS]
md += ["", "## Open questions", ""] + [f"- {q}" for q in OPEN_QUESTIONS]
(NODE / "docs" / "framework_readings.md").write_text("\n".join(md) + "\n")

print(f"framework {framework['framework_version']}: vocabulary={len(VOCAB)} nodes={len(nodes)} "
      f"(in vocabulary {sum(n['in_vocabulary'] for n in nodes.values())}) active={list(active_out)} bridges={len(bridges)}")
