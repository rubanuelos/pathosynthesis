"""Encodings of Rina Nicolae's 26 emotion diagrams (all of them, active or not).

Data only; interpretation/tools/build_framework.py turns this into interpretation/emotion_framework.json.
Each diagram: drawn (what is on the page), reading (our interpretation), gist (one line for prompts),
questions (open checks), resolved (Rubén's answers), relations (typed edges between the diagram's own words).
Relations use the diagram's words, which are not all in the contract's emotion vocabulary; the builder flags which are.
Corrections go here, then re-run the builder.
"""
# ---------------------------------------------------------------- helpers
def child(p, c): return {"type": "child", "parent": p, "child": c}
def orient(f, t): return {"type": "orients_toward", "from": f, "to": t}
def blend(term, a, b): return {"type": "blend", "term": term, "of": [a, b]}
def compound(term, *of, modifier=None, leans_toward=None):
    r = {"type": "compound", "term": term, "of": list(of)}
    if modifier:
        r["modifier"] = modifier
    if leans_toward:
        assert leans_toward in of
        r["leans_toward"] = leans_toward
    return r
def span(term, a, b): return {"type": "span", "term": term, "from": a, "to": b}
def flow(a, b, style="solid"): return {"type": "flows_to", "from": a, "to": b, "style": style}
def ascend(chain): return [{"type": "ascends_to", "from": chain[i], "to": chain[i + 1]} for i in range(len(chain) - 1)]
def nest(chain):  # outermost first
    return [{"type": "contains", "outer": chain[i], "inner": chain[i + 1]} for i in range(len(chain) - 1)]
def signed(a, b, sign, style): return {"type": "signed", "from": a, "to": b, "sign": sign, "style": style}
def quad(term, x, y): return {"type": "quadrant", "term": term, "x": x, "y": y}
def axis(a, b): return {"type": "axis", "poles": [a, b]}
def glyph(term, arrow, ring, gloss): return {"type": "glyph", "term": term, "arrow": arrow, "ring": ring, "gloss": gloss}

def pentagon(vertices, sides, diagonals):
    rels = [blend(t, a, b) for t, (a, b) in sides.items()]
    rels += [blend(t, a, b) for t, (a, b) in diagonals.items()]
    return rels

# ---------------------------------------------------------------- diagrams (image order = upload order 2026-10-18)
D = []

D.append(dict(
    id="uncertainty", image=1, title="uncertainty", grammar="tree", confidence="high",
    drawn="uncertainty, solid fork to threat and opportunity. Dashed lines with arrowheads pointing UP into the middle row: fear, anxiety, vigilance -> threat; excitement, hope, aspiration -> opportunity.",
    reading="Uncertainty forks into two appraisals of one situation. The leaves are felt forms that orient toward (or build) an appraisal, which is why the arrows point up, not down. Because both branches share a root, a feeling can cross the fork without the situation changing: anxiety and excitement are the same uncertainty read two ways. (The anxiety->excitement crossing is my gloss from reappraisal research, not drawn.)",
    gist="Uncertainty is read either as threat (felt as fear, anxiety, vigilance) or as opportunity (felt as excitement, hope, aspiration). Same root, so a feeling can cross the fork.",
    questions=["Arrow direction: I read leaf -> appraisal ('the feeling orients toward / constructs the appraisal'). If it means 'appraisal produces the feeling', the data is unchanged but the prompt wording shifts."],
    relations=[child("uncertainty", "threat"), child("uncertainty", "opportunity")]
    + [orient(x, "threat") for x in ("fear", "anxiety", "vigilance")]
    + [orient(x, "opportunity") for x in ("excitement", "hope", "aspiration")],
))

D.append(dict(
    id="attraction_glyphs", image=2, title="attraction glyphs", grammar="glyph", confidence="medium",
    drawn="Six glyphs, each a black dot with an arrow to a white circle. Dashed rings around one circle; faint grey rings or a faded circle; single vs double-headed arrows. Nicolae's own captions under each.",
    reading="Black = the one who desires, white = the desired. I infer this from 'one entity orients towards another' plus temptation, where the ring sits on the black dot (the desirer's own commitment). Visual grammar: dashed ring = boundary; faint grey = veiled (allure) or degraded (desecration); double arrow = the pull runs both ways (seduction: the desired shapes it; temptation: the desirer is pulled between two claims). The small ticks on seduction's ring I read as a gate, i.e. controlled access.",
    gist="Six shapes of desire meeting an obstacle; definitions are Nicolae's.",
    questions=["Seduction's ring ticks = a gate (controlled access)?"],
    resolved=["Black = desirer, white = desired: confirmed by Rubén, 2026-10-26."],
    relations=[
        glyph("attraction", "one_way", None, "one entity orients towards another"),
        glyph("allure", "one_way", {"on": "desired", "style": "faint dashed halo"}, "attraction intensified by partial concealment or distance"),
        glyph("seduction", "two_way", {"on": "desired", "style": "dashed ring with a gate"}, "the deliberate shaping of another's attraction through controlled access"),
        glyph("temptation", "two_way", {"on": "desirer", "style": "dashed ring"}, "attraction heightened by competing commitment or constraint"),
        glyph("transgression", "one_way", {"on": "desired", "style": "dashed ring"}, "desire to cross a boundary is intensified because it is forbidden"),
        glyph("desecration", "one_way", {"on": "desired", "style": "faint ring, desired faded"}, "desire to violate a boundary to degrade what it protects"),
    ],
))

D.append(dict(
    id="fate_vector", image=3, title="fate / destiny", grammar="vector", confidence="medium",
    drawn="Two concave curves rise from a wide base and converge at a black dot; the region between them is labelled fate. From the dot a straight arrow rises, labelled destiny.",
    reading="Fate is the funnel: many converging forces narrowing possibility to a point. Destiny is the single direction that leaves that point. Fate closes in; destiny goes out.",
    gist="Fate is the narrowing funnel of forces; destiny is the single line that leaves its point.",
    questions=[],
    relations=[flow("fate", "destiny")],
))

D.append(dict(
    id="devotion", image=4, title="devotion", grammar="lattice", confidence="high",
    drawn="DEVOTION -> idealization, imitation, submission, service, understanding (middle). Bottom: romance, fandom, following, worship, care, each wired to several middle terms.",
    reading="A recipe lattice: devotion has five modes; each concrete form of devotion is the mix of the modes wired into it. Lines I traced: romance = idealization + understanding; fandom = idealization + imitation + submission; following = idealization + imitation + submission; worship = idealization + submission + service; care = service + understanding. Fandom and following share a recipe and differ by lean: fandom sits closer to idealization, following closer to submission. The small difference is the meaning.",
    gist="Devotion has five modes; each form of devotion is a recipe of modes. Fandom and following share a recipe and differ only in lean: fandom toward idealization, following toward submission.",
    questions=[],
    resolved=["Fandom and following have the same recipe; fandom leans toward idealization, following toward submission (Rubén, 2026-10-26)."],
    relations=[child("devotion", m) for m in ("idealization", "imitation", "submission", "service", "understanding")] + [
        compound("romance", "idealization", "understanding"),
        compound("fandom", "idealization", "imitation", "submission", leans_toward="idealization"),
        compound("following", "idealization", "imitation", "submission", leans_toward="submission"),
        compound("worship", "idealization", "submission", "service"),
        compound("care", "service", "understanding"),
    ],
))

D.append(dict(
    id="sacred_nest", image=5, title="content to sacred", grammar="nest", confidence="high",
    drawn="Six circles, all tangent at the bottom: content (outermost) > entertainment > culture > tradition > ritual > sacred (innermost).",
    reading="Containment with a shared ground point. Each inner ring is a denser, rarer subset of the outer: the sacred is the most concentrated, content the most diluted. Outward = dilution; inward = condensation. Affectively, the same act can be felt as content or as sacred depending on depth.",
    gist="sacred inside ritual inside tradition inside culture inside entertainment inside content: inward is denser, outward is diluted.",
    questions=[],
    relations=nest(["content", "entertainment", "culture", "tradition", "ritual", "sacred"]),
))

D.append(dict(
    id="play_diamond", image=6, title="play / competence", grammar="signed", confidence="high",
    drawn="Diamond: play (top), grace (left), clumsiness (right), competence (bottom). Solid lines with + from grace and clumsiness up to play; dashed lines with - from both down to competence.",
    reading="The signs are directions on grace and clumsiness together. Acting with more grace and more clumsiness reads as play; acting with less grace and less clumsiness reads as competence: no flourish, no fumble. Play and competence are opposite ends of one move. Agrees with the grace fan (grace + clumsiness = play).",
    gist="More grace and more clumsiness together read as play; less of both reads as competence.",
    questions=[],
    resolved=["+ = more of both -> play; - = less of both -> competence (Rubén, 2026-10-26)."],
    relations=[signed("grace", "play", "+", "solid"), signed("clumsiness", "play", "+", "solid"),
               signed("grace", "competence", "-", "dashed"), signed("clumsiness", "competence", "-", "dashed"),
               {"type": "axis", "poles": ["competence", "play"], "label": "less grace and clumsiness <-> more grace and clumsiness"}],
))

D.append(dict(
    id="will", image=7, title="my will / the will of the world", grammar="nest", confidence="medium",
    drawn="Small circle 'my will' inside a large circle 'the will of the world', tangent at the bottom. Five arrows radiate outward from my will toward the outer circle, stopping short of it.",
    reading="My will is enclosed by the world's will and shares its ground (tangent). It pushes outward in many directions but never reaches the limit (arrows stop short).",
    gist="My will pushes outward inside the will of the world, which holds it and which it never reaches.",
    questions=[],
    relations=nest(["the will of the world", "my will"]),
))

D.append(dict(
    id="consequences", image=8, title="consequences", grammar="quadrant", confidence="high",
    drawn="2x2 titled consequences. Top: followed-through; bottom: forgiven; left: set in advance; right: decided afterwards. Quadrants: prevention (TL), justice (TR), permission (BL), mercy (BR).",
    reading="Two axes: when the consequence is set (in advance / afterwards) and whether it is carried out (followed-through / forgiven).",
    gist="Consequences set in advance and followed through = prevention; decided afterwards and followed through = justice; set in advance and forgiven = permission; decided afterwards and forgiven = mercy.",
    questions=[],
    relations=[quad("prevention", "set in advance", "followed-through"), quad("justice", "decided afterwards", "followed-through"),
               quad("permission", "set in advance", "forgiven"), quad("mercy", "decided afterwards", "forgiven")],
))

D.append(dict(
    id="surplus", image=9, title="surplus", grammar="flow", confidence="medium",
    drawn="production loops on itself (maintenance), sends solid arrows to surplus and reserves, a dashed arrow to leakage. surplus sends solid arrows to seven terms: intensification, differentiation, stabilization, expansion, domination, dissipation, destruction. A dashed path runs intensification -> differentiation -> stabilization -> expansion (side labelled luxury) -> domination -> dissipation -> destruction (side labelled catastrophe).",
    reading="A general economy (it reads to me like Bataille's accursed share). Solid = where excess can be directed; dashed = how one destination tends to slide into the next. Expansion is the hinge between luxury and catastrophe. For us: excess feeling has to be spent somewhere, which is the logic of a 'release' trajectory.",
    gist="Production keeps itself (maintenance), stores (reserves), leaks, or makes surplus. Surplus is spent as intensification, differentiation, stabilization, expansion (luxury) or domination, dissipation, destruction (catastrophe); each slides into the next, with expansion as the hinge.",
    questions=["Solid = directed, dashed = drift: right?"],
    relations=[flow("production", "production", "solid"), flow("production", "surplus"), flow("production", "reserves"), flow("production", "leakage", "dashed")]
    + [flow("surplus", x) for x in ("intensification", "differentiation", "stabilization", "expansion", "domination", "dissipation", "destruction")]
    + [flow(a, b, "dashed") for a, b in [("intensification", "differentiation"), ("differentiation", "stabilization"), ("stabilization", "expansion"),
                                         ("expansion", "domination"), ("domination", "dissipation"), ("dissipation", "destruction")]]
    + [{"type": "region", "term": "luxury", "members": ["intensification", "differentiation", "stabilization"]},
       {"type": "region", "term": "catastrophe", "members": ["domination", "dissipation", "destruction"]},
       {"type": "loop_label", "term": "maintenance", "on": "production"}],
))

D.append(dict(
    id="choice_venn", image=10, title="choice", grammar="venn", confidence="high",
    drawn="Two overlapping circles: it's your choice / it's not your choice. Overlap unlabelled.",
    reading="The unlabelled overlap is the point: things that are both your choice and not. A feeling is in that overlap: you didn't choose it, but you choose what to do with it, which is exactly the piece's intention question.",
    gist="Some things are both your choice and not your choice: a feeling arrives unchosen, what you do with it is chosen.",
    questions=[],
    relations=[{"type": "venn", "sets": ["it's your choice", "it's not your choice"], "overlap": None}],
))

D.append(dict(
    id="commitment", image=11, title="commitment", grammar="lattice", confidence="medium",
    drawn="COMMITMENT -> cost, duration, witness, renunciation, risk. Bottom: sacrifice, investment, oath, marriage, wager.",
    reading="Same recipe lattice as devotion. Lines I traced: sacrifice = cost + renunciation; investment = cost + duration + risk; oath = witness + renunciation; marriage = duration + witness + renunciation; wager = cost + risk. All five recipes are distinct and make sense, so I'm fairly confident.",
    gist="Commitment is made of cost, duration, witness, renunciation and risk; its forms are recipes of these.",
    questions=["Cost -> wager (the long line to the far right): check."],
    relations=[child("commitment", m) for m in ("cost", "duration", "witness", "renunciation", "risk")] + [
        compound("sacrifice", "cost", "renunciation"),
        compound("investment", "cost", "duration", "risk"),
        compound("oath", "witness", "renunciation"),
        compound("marriage", "duration", "witness", "renunciation"),
        compound("wager", "cost", "risk"),
    ],
))

DESIRE_STAGES = ["lack", "attraction", "fantasy", "pursuit", "possession"]
D.append(dict(
    id="desire_arcs", image=12, title="desire (Fig 1)", grammar="arcs", confidence="medium",
    drawn="Baseline LACK, ATTRACTION, FANTASY, PURSUIT, POSSESSION. Arcs anchored at LACK end at attraction, fantasy, pursuit; arcs anchored at POSSESSION start at pursuit, fantasy, attraction; one outer arc spans everything. Labels sit in the regions.",
    reading="Every arc is anchored at one end of the baseline. Arcs from LACK (longing, wishing, seeking) are desire defined by what is missing; arcs from POSSESSION (conquest, projection, attachment) are desire defined by having or holding. The three middle regions are overlaps of a lack-arc and a possession-arc (infatuation, seduction, ambition): desire that is missing and already grasping. A feeling here is a stretch of the journey, not a point, so it can widen or slide along the baseline.",
    gist="Desire runs lack -> attraction -> fantasy -> pursuit -> possession. Each feeling covers a stretch: from the lack end (longing, wishing, seeking), from the possession end (conquest, projection, attachment), or the overlaps in between (infatuation, seduction, ambition).",
    questions=["I read each label as the region inside its arc but outside the arcs nested in it (so 'wishing' = lack->fantasy minus longing). Spans below are the arcs' full extents."],
    axis=DESIRE_STAGES, isomorphic_with="fate_arcs",
    relations=[span("longing", "lack", "attraction"), span("wishing", "lack", "fantasy"), span("seeking", "lack", "pursuit"),
               span("infatuation", "attraction", "fantasy"), span("seduction", "attraction", "pursuit"), span("ambition", "fantasy", "pursuit"),
               span("attachment", "attraction", "possession"), span("projection", "fantasy", "possession"), span("conquest", "pursuit", "possession"),
               span("desire", "lack", "possession")],
))

D.append(dict(
    id="future_shaping", image=13, title="future shaping", grammar="tree", confidence="high",
    drawn="future shaping, directed by: self (dashed), others (bold, solid), environment (dashed), with dashed double arrows self <-> others <-> environment. Only 'others' is expanded: possibility and tendency, joined by a dashed double arrow 'degree of influence'. possibility -> prohibition, permission, obligation; tendency -> coercion, persuasion, influence.",
    reading="Only the 'others' branch is developed. Possibility shapes what is allowed (deontic); tendency shapes what is likely. I read each triple as a gradient: prohibition / permission / obligation (forbidden, allowed, required) and coercion / persuasion / influence (hard to soft).",
    gist="The future is shaped by self, others or environment. Others shape it through possibility (prohibition, permission, obligation) or tendency (coercion, persuasion, influence).",
    questions=["Are the triples gradients (left-to-right), or just siblings?"],
    relations=[child("future shaping", x) for x in ("self", "others", "environment")]
    + [child("others", "possibility"), child("others", "tendency")]
    + [child("possibility", x) for x in ("prohibition", "permission", "obligation")]
    + [child("tendency", x) for x in ("coercion", "persuasion", "influence")]
    + [{"type": "axis", "poles": ["possibility", "tendency"], "label": "degree of influence"}],
))

D.append(dict(
    id="power_pentagon", image=14, title="power pentagon", grammar="pentagon", confidence="high",
    drawn="Vertices POWER, DESIRE, FRAGILITY, AMBIGUITY, RECOGNITION. All ten lines (5 sides, 5 star diagonals) carry a label.",
    reading="Each line is the blend of its two endpoints. Ten pairs, ten names, nothing missing. This is the mixture idea drawn directly.",
    gist="Each line names the blend of its two vertices.",
    questions=[],
    vertices=["power", "desire", "fragility", "ambiguity", "recognition"],
    relations=pentagon(None,
        {"charisma": ("power", "desire"), "dependency": ("desire", "fragility"), "hypervigilance": ("fragility", "ambiguity"),
         "illegibility": ("ambiguity", "recognition"), "legitimacy": ("recognition", "power")},
        {"mystique": ("power", "ambiguity"), "precarity": ("power", "fragility"), "exhibition": ("recognition", "desire"),
         "insecurity": ("recognition", "fragility"), "fantasy": ("desire", "ambiguity")}),
))

D.append(dict(
    id="indirect_action", image=15, title="indirect action", grammar="lattice", confidence="medium",
    drawn="INDIRECT ACTION -> messages, symbols, framing, timing, rules. Bottom: seduction, advertising, ritual, diplomacy, magic.",
    reading="Recipe lattice again. Traced: seduction = messages + framing + timing; advertising = messages + symbols + framing; ritual = symbols + timing + rules; diplomacy = messages + timing + rules; magic = symbols + rules.",
    gist="Indirect action works through messages, symbols, framing, timing and rules; its forms are recipes of these.",
    questions=["Most crossing lines of the three lattices; please check."],
    relations=[child("indirect action", m) for m in ("messages", "symbols", "framing", "timing", "rules")] + [
        compound("seduction", "messages", "framing", "timing"),
        compound("advertising", "messages", "symbols", "framing"),
        compound("ritual", "symbols", "timing", "rules"),
        compound("diplomacy", "messages", "timing", "rules"),
        compound("magic", "symbols", "rules"),
    ],
))

D.append(dict(
    id="desire_pentagon", image=16, title="desire pentagon", grammar="pentagon", confidence="high",
    drawn="Vertices DESIRE, TABOO, COMPULSION, ESCALATION, LACK. All ten lines labelled.",
    reading="Each line is the blend of its two endpoints. Longing = desire + lack here, agreeing with the desire arcs (longing spans lack -> attraction) and the mystery pentagon (longing = absence + desire).",
    gist="Each line names the blend of its two vertices.",
    questions=["Terms like addiction, perversion, compulsion: I keep them in the vocabulary as felt qualities, and the prompt forbids using them as labels about the person. Or drop them from the mixture vocabulary?"],
    vertices=["desire", "taboo", "compulsion", "escalation", "lack"],
    relations=pentagon(None,
        {"temptation": ("desire", "taboo"), "perversion": ("taboo", "compulsion"), "spiral": ("compulsion", "escalation"),
         "greed": ("escalation", "lack"), "longing": ("lack", "desire")},
        {"repression": ("lack", "taboo"), "urge": ("desire", "escalation"), "obsession": ("desire", "compulsion"),
         "addiction": ("lack", "compulsion"), "transgression": ("taboo", "escalation")}),
))

D.append(dict(
    id="ascent_ladders", image=17, title="four ascents", grammar="ladder", confidence="medium",
    drawn="Four slanted lines with arrows at the top. safety -> comfort -> serenity -> peace; meaning -> significance -> sacredness -> revelation; status -> admiration -> glory -> transcendence; belonging -> intimacy -> communion -> union. The bases are spread wide; the summits sit close together.",
    reading="Four needs, each intensifying upward into a culminating state. The lines lean inward, so the summits (peace, revelation, transcendence, union) almost touch: different starting needs converging at the top. Good candidates for resurface endpoints.",
    gist="Four ascents from a need to a summit: safety -> comfort -> serenity -> peace; meaning -> significance -> sacredness -> revelation; status -> admiration -> glory -> transcendence; belonging -> intimacy -> communion -> union. The summits nearly meet.",
    questions=["Is the convergence of the summits intentional?"],
    relations=ascend(["safety", "comfort", "serenity", "peace"]) + ascend(["meaning", "significance", "sacredness", "revelation"])
    + ascend(["status", "admiration", "glory", "transcendence"]) + ascend(["belonging", "intimacy", "communion", "union"]),
))

D.append(dict(
    id="existence_nest", image=18, title="existence to execution", grammar="nest", confidence="high",
    drawn="Five circles tangent at the bottom: existence > meaning > structure > strategy > execution.",
    reading="Outer = more fundamental, contains the inner. Parallels 'levels of power' (existence ~ being, structure ~ protocol).",
    gist="execution inside strategy inside structure inside meaning inside existence.",
    questions=[],
    relations=nest(["existence", "meaning", "structure", "strategy", "execution"]),
))

D.append(dict(
    id="spectacle_fan", image=19, title="spectacle", grammar="fan", confidence="high",
    drawn="spectacle at top; nine lines, each labelled '+ x', to: circus, ritual, carnival, disaster porn, ceremony, identity theater, luxury, bloodsport, sport.",
    reading="Base + modifier = compound. Ritual = spectacle + devotion links to the devotion lattice; luxury links to surplus.",
    gist="spectacle + modifier = form.",
    questions=[],
    relations=[compound(t, "spectacle", m, modifier=m) for m, t in [
        ("abnormality", "circus"), ("devotion", "ritual"), ("norm suspension", "carnival"), ("collapse", "disaster porn"),
        ("power", "ceremony"), ("identity", "identity theater"), ("wealth", "luxury"), ("violence", "bloodsport"), ("competition", "sport")]],
))

D.append(dict(
    id="intention_nest", image=20, title="intention to nature", grammar="nest", confidence="high",
    drawn="Five circles tangent at the LEFT: intention (innermost) < action < behavior < habit < nature.",
    reading="Unlike the bottom-tangent nests, these grow rightward from a shared left point, which reads as time: an intention repeated becomes action, behavior, habit, nature. For us: the visitor's 'intention' is the smallest ring; the piece works at that scale, not at the scale of habit.",
    gist="intention grows into action, behavior, habit, nature (each containing the last).",
    questions=[],
    relations=nest(["nature", "habit", "behavior", "action", "intention"]),
))

D.append(dict(
    id="levels_of_power", image=21, title="levels of power", grammar="ladder", confidence="high",
    drawn="LEVELS OF POWER, 0-5, dotted arrows flowing down: void (filled black), being, meaning, protocol, strategy, execution. Nicolae's gloss for each.",
    reading="Power flows downward; each level constrains the next. Void is the only filled shape: that which precedes being. Parallels the existence nest.",
    gist="Power flows down: void -> being -> meaning -> protocol -> strategy -> execution.",
    questions=[],
    glosses={"void": "that which precedes all being", "being": "what can exist and be named", "meaning": "what has value and importance",
             "protocol": "what is allowed and incentivized", "strategy": "what can be done within constraint", "execution": "what becomes real in the world"},
    relations=[flow(a, b, "dotted") for a, b in [("void", "being"), ("being", "meaning"), ("meaning", "protocol"), ("protocol", "strategy"), ("strategy", "execution")]],
))

D.append(dict(
    id="grace_fan", image=22, title="grace", grammar="fan", confidence="high",
    drawn="grace at top; seven lines labelled '+ x' to: prowess, recovery, dignity, play, reflex, restraint, harmony.",
    reading="Base + modifier = compound. Grace + clumsiness = play agrees with the play diamond.",
    gist="grace + modifier = quality.",
    questions=[],
    relations=[compound(t, "grace", m, modifier=m) for m, t in [
        ("power", "prowess"), ("error", "recovery"), ("suffering", "dignity"), ("clumsiness", "play"),
        ("urgency", "reflex"), ("refusal", "restraint"), ("multiplicity", "harmony")]],
))

D.append(dict(
    id="desire_tree", image=23, title="desire tree", grammar="tree", confidence="high",
    drawn="desire -> appetite, violation. appetite -> attraction, allure, seduction, temptation. violation -> temptation, transgression, desecration. The two brackets meet inside the word 'temptation'.",
    reading="Same six terms as the glyphs, sorted into appetite (wanting) and violation (wanting to cross). Temptation belongs to both: the hinge where wanting starts to press on a boundary.",
    gist="Desire splits into appetite (attraction, allure, seduction, temptation) and violation (temptation, transgression, desecration). Temptation is the hinge.",
    questions=[],
    relations=[child("desire", "appetite"), child("desire", "violation")]
    + [child("appetite", x) for x in ("attraction", "allure", "seduction", "temptation")]
    + [child("violation", x) for x in ("temptation", "transgression", "desecration")],
))

FATE_STAGES = ["inheritance", "chance", "choice", "necessity", "pattern"]
D.append(dict(
    id="fate_arcs", image=24, title="fate (Fig 2)", grammar="arcs", confidence="medium",
    drawn="Same geometry as Fig 1. Baseline INHERITANCE, CHANCE, CHOICE, NECESSITY, PATTERN. Labels: lot, tradition, birthright, gamble, destiny, commitment, synchronicity (spelled SYNCHONICITY), preference, law.",
    reading="Lot, tradition, birthright are anchored at inheritance; law, preference, synchronicity at pattern; gamble, destiny, commitment are the overlaps. Because Fig 1 and Fig 2 share geometry they align position by position: lack~inheritance, attraction~chance, fantasy~choice, pursuit~necessity, possession~pattern. So seduction sits where destiny sits and ambition where commitment sits.",
    gist="Fate runs inheritance -> chance -> choice -> necessity -> pattern; lot, tradition, birthright, gamble, destiny, commitment, synchronicity, preference and law each cover a stretch.",
    questions=["Typo normalized to 'synchronicity'.", "Is the Fig 1/Fig 2 correspondence meant to be read across?"],
    axis=FATE_STAGES, isomorphic_with="desire_arcs",
    relations=[span("lot", "inheritance", "chance"), span("tradition", "inheritance", "choice"), span("birthright", "inheritance", "necessity"),
               span("gamble", "chance", "choice"), span("destiny", "chance", "necessity"), span("commitment", "choice", "necessity"),
               span("synchronicity", "chance", "pattern"), span("preference", "choice", "pattern"), span("law", "necessity", "pattern"),
               span("fate", "inheritance", "pattern")],
))

D.append(dict(
    id="mystery_pentagon", image=25, title="mystery pentagon", grammar="pentagon", confidence="high",
    drawn="Vertices MYSTERY, DESIRE, VULNERABILITY, HOPE, ABSENCE. All ten lines labelled.",
    reading="Each line is the blend of its two endpoints. The most useful single diagram for us: loss (absence + vulnerability), disappointment (hope + vulnerability), patience, faith, awe, longing.",
    gist="Each line names the blend of its two vertices.",
    questions=[],
    vertices=["mystery", "desire", "vulnerability", "hope", "absence"],
    relations=pentagon(None,
        {"allure": ("mystery", "desire"), "need": ("desire", "vulnerability"), "disappointment": ("vulnerability", "hope"),
         "patience": ("hope", "absence"), "void": ("absence", "mystery")},
        {"longing": ("absence", "desire"), "faith": ("mystery", "hope"), "awe": ("mystery", "vulnerability"),
         "loss": ("absence", "vulnerability"), "expectation": ("hope", "desire")}),
))

D.append(dict(
    id="ways_to_do_things", image=26, title="ways to do things", grammar="axes", confidence="high",
    drawn="Six double-headed axes: clumsy-graceful, strained-easy, hesitant-decisive, rigid-flexible, insincere-genuine, reckless-considerate.",
    reading="Not emotions but manners: how something is done. I use them as the bridge vocabulary in palette.md (how a movement unfolds), not in mixtures.",
    gist="Manners, as poles: clumsy/graceful, strained/easy, hesitant/decisive, rigid/flexible, insincere/genuine, reckless/considerate.",
    questions=[],
    relations=[axis(a, b) for a, b in [("clumsy", "graceful"), ("strained", "easy"), ("hesitant", "decisive"),
                                       ("rigid", "flexible"), ("insincere", "genuine"), ("reckless", "considerate")]],
))

assert len(D) == 26 and [d["image"] for d in D] == list(range(1, 27))

FILES = ["uncertainty-develop", "attraction-identification", "fate-engage", "devotion-commit", "content-detail", "competence-play",
         "will-project", "consequence-deal", "abundance-blossom", "reality-influence", "commitment-levels", "desire-amplify",
         "future-shaping", "drive-identify", "indirect-act", "desire-indulge", "confidence-hone", "routine-build", "spectacle-map",
         "habit-build", "power-develop", "grace-development", "desire-control", "fate-control", "mystery-engage", "boundary-setting"]
for d, f in zip(D, FILES):
    d["file"] = f"chthonic-youth-diagrams/{f}.png"

# contract v0.3 uses file slugs as diagram ids; keep the old ids as aliases
for d in D:
    d["alias"] = d["id"]
    d["id"] = d["file"].split("/")[-1][:-4]
BY_ALIAS = {d["alias"]: d["id"] for d in D}
for d in D:
    if "isomorphic_with" in d:
        d["isomorphic_with"] = BY_ALIAS[d["isomorphic_with"]]
