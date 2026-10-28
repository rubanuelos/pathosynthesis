// sound/mystery-engage.scd — STUB, not composed. Registered so select/position dispatch already works.
// Positions (contract/diagrams.json, radial from the pentagram's centre):
//   0 star chords: longing, faith, awe, loss, expectation
//   1 pentagon sides: void, allure, need, disappointment, patience
//   2 vertices: mystery, desire, vulnerability, hope, absence
// Several positions share a level here, so `at` matters as much as `level`.
// To compose: follow habit-build.scd's shape (see fate-engage.scd's header).
(
~diagrams = ~diagrams ?? { () };
~diagrams[\mysteryEngage] = (
	start:    { "mystery-engage: start (stub, silent)".postln },
	stop:     { |rel = 3| },
	position: { |at, level, levels, depth|
		"mystery-engage: % (level % of %, depth %) — stub".format(at, level, levels, depth).postln },
);
)
