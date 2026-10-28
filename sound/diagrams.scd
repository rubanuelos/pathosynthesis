// sound/diagrams.scd — the diagram registry and its dispatch (contract v0.3 §4).
// Loaded by main.scd after config.scd, before the patch files.
//
// Each patch file registers itself:
//   ~diagrams[\habitBuild] = (
//       start:    { ... },                              // routine on, fx on, short fade-in
//       stop:     { |rel = 3| ... },                    // fade over rel s, then free; rel 0 = at once
//       position: { |at, level, levels, depth| ... },   // what a level sounds like is the patch's business
//   );
// OSC names map to keys by camel case: 'habit-build' → \habitBuild. Entries are called with .value
// (not as Event methods), so `position` receives exactly (at, level, levels, depth).
// One diagram plays at a time (~diagramActive). A patch writes its mono sum to ~pathosBus[\room],
// multiplied by In.kr(~pathosMasterBus); see habit-build.scd.
(
~diagrams = ~diagrams ?? { () };
~diagramActive = nil;

~diagramKey = { |name|
	var w = (name ? "").asString.split($-);
	(w[0] ++ w.drop(1).collect { |x| x[0].toUpper ++ x.drop(1) }.join).asSymbol
};

~diagramStop = { |rel = 3|
	~diagramActive !? { |k| ~diagrams[k] !? { |e| e[\stop].value(rel) } };
	~diagramActive = nil;
};

// /pathos/diagram/select diagram:s — sent once per score, before mirror.
OSCdef(\pathosDiagramSelect, { |m|
	var key = ~diagramKey.(m[1]), entry = ~diagrams[key];
	if(key == ~diagramActive) {
		"[diagram] % already playing".format(m[1]).postln;
	} {
		~diagramStop.(3);   // another diagram stops the current one
		if(entry.isNil) {
			"[diagram] no patch registered for '%'".format(m[1]).warn;
		} {
			~diagramActive = key;
			"[diagram] select %".format(m[1]).postln;
			entry[\start].value;
		};
	};
}, '/pathos/diagram/select');

// /pathos/diagram/position diagram:s at:s level:i levels:i depth:f — start of every movement, after the lag.
OSCdef(\pathosDiagramPosition, { |m|
	var key = ~diagramKey.(m[1]);
	if(key != ~diagramActive) {
		"[diagram] position for '%' ignored: active is %".format(m[1], ~diagramActive).warn;
	} {
		~diagrams[key][\position].value(m[2], (m[3] ? 0).asInteger, (m[4] ? 1).asInteger, (m[5] ? 0).asFloat);
	};
}, '/pathos/diagram/position');

// Silent in idle / asking / composing; panic stops in 0.5 s.
OSCdef(\pathosDiagramState, { |m|
	if(~pathosSilentStates.includes(m[1])) { ~diagramStop.(3) };
}, '/pathos/state');

OSCdef(\pathosDiagramPanic, { ~diagramStop.(~pathosPanicFade) }, '/pathos/panic');
)
