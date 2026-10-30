// sound/mystery-engage.scd — mystery-engage patch, wired into the diagram registry (contract v0.3 §3.2, §4).
// Loaded by main.scd after diagrams.scd. Concept and numbers: sound/docs/diagram_translations.md.
//
// THE FIGURE (interpretation/docs/active_diagrams.md): a pentagon with a star inside it. Vertices are single
// ingredients (mystery, desire, vulnerability, hope, absence). Each of the ten lines is the mixture of its two
// ends: the five sides mix neighbours (level 1), the five star lines mix far-apart ingredients and cross the
// centre (level 0). Outside is one clear feeling; the centre is two far-apart feelings held at once.
//
// THE SOUND: one granular voice per vertex, all five within 90 cents of each other (~mystery[\spreadCents]).
//   vertex (level 2)  one pitch, the other four only as a faint halo: almost no beating. Clarity, never purity.
//   line (levels 0-1) its two vertex pitches at equal weight: they beat at their difference frequency.
//                     The beating IS the friction of the mixture. Star lines join pitches that are, on
//                     average, farther apart than sides, so the centre of the figure beats faster.
//   moving            the vertex voices crossfade over the orchestrator's lag (equal power). Along a shared
//                     vertex (loss -> patience keeps absence) one pitch stays and the other is replaced, so for
//                     the length of the glide three pitches beat at once.
// The five pitches sit on a Golomb ruler (marks 0 1 4 9 11): all ten pairwise distances differ, so each of the
// ten lines has its own beat speed. No two mixtures in the figure sound alike.
//
// Signal path:  5 phase-continuous sines (x1, x2, x3 partials) → GrainIn clouds + a thin continuous bed
//               → LPF, FreeVerb → × fade env × master → ~pathosBus[\room] → R guard.
// The grains window a continuous sum, so they never reset the phase between pitches: the beating survives
// the granulation and is heard as the cloud swelling and thinning.
//
// Score words this patch reads (contract §4 "diagram patches may use or ignore"):
//   /pathos/diagram/position  at → which vertices sound; level is implied by `at`
//   /pathos/vial/chord        density → grain overlap · brightness → grain length, upper partials, LPF ·
//                             tension → how still the balance of a line is (high = locked 50/50, deepest beats)
//   /pathos/state dwell       time dilation: the whole ruler shrinks (beats slow by the same factor) and
//                             grains lengthen. The mixture stays the same mixture, its clock slows.
//   ignores /pathos/vial/voices and register (the vertices are the harmony; see ~mystery[\followRegister])
//
// Test alone (after main.scd):  ~mysteryTour.reset.play;  ~mysteryTransmuteTest.reset.play;  ~mysteryTestStop.();
// Full scores with chair:      (sound/test/scores_mystery-engage.scd).load  (see that file)
(
// ---- composer hooks -------------------------------------------------------------------------
~mystery = ~mystery ?? { () };
~mystery[\amp] = 0.06;                // patch gain before master and the room guard (≈ −29 LUFS; habit-build ≈ −33)
~mystery[\fadeIn] = 4;                // s, on start
~mystery[\centreHz] = 220;            // centre of the five pitches
~mystery[\spreadCents] = 90;          // lowest → highest vertex (if you meant ±90, set 180)
~mystery[\followRegister] = false;    // true: centre = /pathos/vial/chord root × 2 (110 / 220 / 440 Hz)
~mystery[\halo] = 0.12;               // amplitude of the four other vertices at a vertex (0 = pure single pitch)
~mystery[\lineHalo] = 0.05;           // amplitude of the three uninvolved vertices on a line
~mystery[\dwellDilation] = 0.5;       // in dwell: ruler × this (all beats slow by this factor), grains longer
~mystery[\bed] = 0.12;                // continuous (un-granulated) sine bed under the grains

// Vertex marks on the ruler (0 … ~mystery[\rulerLength]). Golomb ruler {0 1 4 9 11}: every pair differs.
// Chosen so the lines read in this order of beat speed (slow → fast):
//   void 1 · need 2 · faith 3 · patience 4 · expectation 5 · disappointment 7 · allure 8 · longing 9 · awe 10 · loss 11
~mystery[\marks] = (absence: 0, mystery: 1, hope: 4, desire: 9, vulnerability: 11);
~mystery[\rulerLength] = 11;

// From contract/diagrams.json (mystery-engage positions). Pentagon order, clockwise from the top.
~mystery[\vertices] = [\mystery, \desire, \vulnerability, \hope, \absence];
~mystery[\edges] = (
	longing: [\absence, \desire],   faith: [\mystery, \hope],   awe: [\mystery, \vulnerability],
	loss: [\absence, \vulnerability], expectation: [\desire, \hope],
	void: [\mystery, \absence],     allure: [\mystery, \desire], need: [\desire, \vulnerability],
	disappointment: [\vulnerability, \hope], patience: [\hope, \absence]
);

// Position → weight per vertex (power, sums to ~1). Rewrite freely: this is where a position becomes sound.
~mystery[\weightsFor] = { |at|
	var v = ~mystery[\vertices], edge = ~mystery[\edges][at], h;
	case
	{ v.includes(at) } { h = ~mystery[\halo].squared; v.collect { |x| if(x == at) { 1 } { h } } }
	{ edge.notNil }    { h = ~mystery[\lineHalo].squared; v.collect { |x| if(edge.includes(x)) { 0.5 } { h } } };
	// unknown position → nil
};

// /pathos/vial/chord numbers → synth controls. Rewrite freely.
~mystery[\fromChord] = { |root, density, brightness, tension|
	var e = (
		overlap:  density.linexp(0.2, 0.85, 1.4, 6),         // sparse = separate particles, thick = a continuous cloud
		grainDur: brightness.linexp(0.1, 0.9, 0.2, 0.06),     // dark = long soft grains, bright = short glints
		bright:   brightness,                                 // upper partials (x2, x3) and LPF
		drift:    (1 - tension).clip(0, 1) * 0.6              // how far the two ingredients of a line drift in balance
	);
	if(~mystery[\followRegister]) { e[\centre] = root * 2 };
	e
};

// ---- synth ----------------------------------------------------------------------------------
SynthDef(\mysteryVoice, { |out, masterBus, gate = 1, atk = 4, rel = 3, amp = 0.06, lag = 4,
		centre = 220, spread = 90, dil = 1,
		overlap = 2.5, grainDur = 0.12, bright = 0.35, drift = 0.3, bed = 0.12|
	var marks = \marks.kr([1, 9, 11, 4, 0] / 11);            // ruler position 0-1 per vertex (set from ~mystery[\marks])
	var w     = VarLag.kr(\w.kr(0 ! 5), lag, warp: \sine);    // the crossfade between positions
	var dilL  = VarLag.kr(dil, lag, warp: \sine);
	var cents = (marks - 0.5) * Lag2.kr(spread, 1) * dilL;
	var freqs = Lag2.kr(centre, lag * 0.5) * (cents / 100).midiratio;
	var sway  = LFNoise2.kr({ ExpRand(0.03, 0.06) } ! 5) * VarLag.kr(drift, lag);
	var amps  = (w * (1 + sway)).max(0).sqrt;                  // equal-power
	var l1 = (SinOsc.ar(freqs, { Rand(0, 2pi) } ! 5) * amps).sum;
	var l2 = (SinOsc.ar(freqs * 2, { Rand(0, 2pi) } ! 5) * amps).sum;
	var l3 = (SinOsc.ar(freqs * 3, { Rand(0, 2pi) } ! 5) * amps).sum;
	var ov  = Lag2.kr(overlap, lag);
	var gd  = Lag2.kr(grainDur, lag) / dilL.pow(0.6);
	var brt = Lag2.kr(bright, lag);
	var cloud = { |sig, d, o|                                  // Hann grains windowing a continuous signal
		var t = Dust.ar(o / d);
		GrainIn.ar(1, t, d * TExpRand.ar(0.6, 1.6, t), sig) / (o * 0.5)
	};
	var env = EnvGen.kr(Env.asr(atk, 1, rel, \sine), gate, doneAction: 2);
	var sig = cloud.(l1, gd, ov)
		+ (cloud.(l2, gd * 0.6, ov * 0.7) * brt * 0.45)
		+ (cloud.(l3, gd * 0.4, ov * 0.5) * brt.squared * 0.3)
		+ (l1 * Lag2.kr(bed, lag));
	sig = LPF.ar(HPF.ar(sig, 70), brt.linexp(0, 1, 1600, 7000));
	sig = FreeVerb.ar(sig, 0.38, 0.88, 0.45);
	sig = Limiter.ar(sig * env * amp, 0.35, 0.02);          // rare grain clusters; the room guard stays the last resort
	Out.ar(out, sig * In.kr(masterBus, 1));
}).add;

// ---- state ----------------------------------------------------------------------------------
~mystery[\at] = nil;

~mystery[\freqs] = { |dil = 1|
	var m = ~mystery, spread = m[\spreadCents] * dil;
	m[\vertices].collect { |v| (v -> (m[\centre] ? m[\centreHz] * (((m[\marks][v] / m[\rulerLength]) - 0.5) * spread / 100).midiratio)) }
};

~mystery[\describe] = { |at|
	var f = ~mystery[\freqs].(~mystery[\dil] ? 1).asDict, edge = ~mystery[\edges][at];
	if(edge.notNil) {
		"% + % = %/% Hz → beats % Hz".format(edge[0], edge[1], f[edge[0]].round(0.1), f[edge[1]].round(0.1),
			(f[edge[0]] - f[edge[1]]).abs.round(0.01))
	} { "% alone: % Hz (halo %)".format(at, f[at].round(0.1), ~mystery[\halo]) }
};

// ---- registry entry (called by diagrams.scd) ------------------------------------------------
~diagrams = ~diagrams ?? { () };
~diagrams[\mysteryEngage] = (
	start: {
		var m = ~mystery;
		m[\stopNow].();
		m[\centre] = m[\centreHz]; m[\dil] = 1; m[\at] = nil;
		m[\synth] = Synth(\mysteryVoice, [
			out: ~pathosBus[\room], masterBus: ~pathosMasterBus, amp: m[\amp], atk: m[\fadeIn],
			centre: m[\centreHz], spread: m[\spreadCents], bed: m[\bed], lag: ~pathosLag,
			marks: m[\vertices].collect { |v| m[\marks][v] / m[\rulerLength] },
		], ~pathosGroup[\src]);
		"mystery-engage: start".postln;
	},
	stop: { |rel = 3|
		var syn = ~mystery[\synth];
		~mystery[\synth] = nil;
		if(syn.notNil) {
			if(rel <= 0) { syn.free } { syn.set(\rel, rel, \gate, 0) };
			"mystery-engage: stop (% s)".format(rel).postln;
		};
	},
	position: { |at, level, levels, depth|
		var key = at.asSymbol, w = ~mystery[\weightsFor].(key);
		if(w.isNil) {
			"mystery-engage: unknown position '%' — kept %".format(at, ~mystery[\at]).warn;
		} {
			~mystery[\at] = key;
			~mystery[\synth] !? { |x| x.set(\lag, ~pathosLag, \w, w) };
			"mystery-engage: % (level %) · %".format(at, level, ~mystery[\describe].(key)).postln;
		};
	},
);
~mystery[\stopNow] = { ~diagrams[\mysteryEngage][\stop].value(0) };

// ---- extra score words (existing addresses; acts only while this diagram is active) -----------
OSCdef(\mysteryChord, { |m|
	if(~diagramActive == \mysteryEngage and: { ~mystery[\synth].notNil }) {
		var e = ~mystery[\fromChord].(m[1] ? 110, m[2] ? 0.5, m[3] ? 0.35, m[4] ? 0.5);
		e[\centre] !? { |c| ~mystery[\centre] = c };
		~mystery[\synth].set(\lag, ~pathosLag, *e.asKeyValuePairs);
	};
}, '/pathos/vial/chord');

OSCdef(\mysteryState, { |m|
	if(~diagramActive == \mysteryEngage and: { ~mystery[\synth].notNil }
		and: { ~pathosSilentStates.includes(m[1]).not }) {
		~mystery[\dil] = if(m[1] == \dwell) { ~mystery[\dwellDilation] } { 1 };
		~mystery[\synth].set(\lag, ~pathosLag, \dil, ~mystery[\dil]);
	};
}, '/pathos/state');

if(~pathosLoading != true) { ~mystery[\stopNow].() };          // re-evaluating this file mid-play

// ---- standalone tests (fake the orchestrator; run main.scd first) ---------------------------
// Each step: [phase, at, level, lag s, hold s]. Only select, lag, state and position are sent here:
// the chord stays at its defaults. sound/test/scores_mystery-engage.scd sends full movements.
~mysteryWalk = { |steps|
	Routine {
		var me = NetAddr.localAddr;
		~pathosFakeKeepalive.(true);
		me.sendMsg('/pathos/global/lag', 3);
		me.sendMsg('/pathos/global/master', 1.0);
		me.sendMsg('/pathos/diagram/select', "mystery-engage");
		steps.do { |st|
			me.sendMsg('/pathos/global/lag', st[3]);
			me.sendMsg('/pathos/state', st[0]);
			me.sendMsg('/pathos/diagram/position', "mystery-engage", st[1], st[2], 3, st[2] / 2);
			st[4].wait;
		};
		me.sendMsg('/pathos/global/lag', 6);
		me.sendMsg('/pathos/global/master', 0.0);
		me.sendMsg('/pathos/state', "idle");
		6.wait;
		~pathosFakeKeepalive.(false);
		"[mystery] test done".postln;
	}
};
// Every position: the five vertices (no beating), then the five sides, then the five star lines.
~mysteryTour = ~mysteryWalk.(
	[\mystery, \desire, \vulnerability, \hope, \absence].collect { |v| [\transform, v, 2, 3, 10] }
	++ [\void, \allure, \need, \disappointment, \patience].collect { |v| [\transform, v, 1, 3, 12] }
	++ [\faith, \expectation, \longing, \awe, \loss].collect { |v| [\transform, v, 0, 3, 12] }
);
// The path of contract/examples/score_mystery_engage_transmute.json (absence → loss → patience → hope),
// with its lags and a compressed hold. The dwell on loss slows every beat by ~mystery[\dwellDilation].
~mysteryTransmuteTest = ~mysteryWalk.([
	[\mirror, \absence, 2, 4, 30], [\dwell, \loss, 0, 12, 45], [\transform, \patience, 1, 12, 45],
	[\resurface, \hope, 2, 4, 30]]);
~mysteryTestStop = {
	[~mysteryTour, ~mysteryTransmuteTest].do(_.stop);
	~pathosFakeKeepalive.(false);
	NetAddr.localAddr.sendMsg('/pathos/state', "idle");
};
)
