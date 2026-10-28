// sound/fate-engage.scd — STUB, not composed. Registered so select/position dispatch already works.
// Positions (contract/diagrams.json, vertical, bottom → top): fate 0 · point 1 · destiny 2.
// To compose: follow habit-build.scd's shape — own private bus and groups under ~pathosGroup,
// mono sum × In.kr(~pathosMasterBus) → ~pathosBus[\room], stop(rel) fades then frees, rel 0 = at once.
// Use SynthDef names of its own (habit-build already uses \clip).
(
~diagrams = ~diagrams ?? { () };
~diagrams[\fateEngage] = (
	start:    { "fate-engage: start (stub, silent)".postln },
	stop:     { |rel = 3| },
	position: { |at, level, levels, depth|
		"fate-engage: % (level % of %, depth %) — stub".format(at, level, levels, depth).postln },
);
)
