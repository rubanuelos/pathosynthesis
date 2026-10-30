// sound/fate-engage.scd — fate-engage patch, wired into the diagram registry (contract v0.3 §3.2, §4).
// Loaded by main.scd after diagrams.scd. Concept and numbers: sound/docs/diagram_translations.md.
//
// THE FIGURE (interpretation/docs/active_diagrams.md): two curves rise from a wide base and bend inward until
// they meet at a black dot; an arrow leaves the dot upward. fate (level 0) is the open field between the curves:
// forces converging from both sides, not chosen. point (level 1) is the dot: the narrowest place, pressure.
// destiny (level 2) is the arrow: one direction. Bottom to top: undergoing, converging, directing; many → one.
//
// THE SOUND: brown noise, always, and nothing else. Brown noise is the sound model of Brownian motion: a
// particle in water pushed around by countless collisions it cannot see. Moving up the figure only FILTERS it:
// seven resonant bands at the first seven harmonics of f0 (just intonation by definition: 1:2:3:4:5:6:7)
// narrow until only those harmonics are left. Nothing is added on the way up; destiny was inside the noise.
//   fate     wide bands + raw noise: the field. Each band swells on its own (many separate fates).
//   point    bands narrow to the threshold where noise becomes pitch. Their centres are still pulled off
//            the harmonics, odd ones from below and even ones from above (the two curves), and are converging.
//   destiny  bands a few Hz wide, exactly on the harmonics, tilted brighter: an upward series, the arrow.
//            All seven share one granular envelope, so they fuse into one voice. Perception calls the rule
//            that binds parts into one object "common fate" (Gestalt; Bregman's auditory scene analysis).
// The bandwidth glides on a log scale (equal ratios per second), like the curves that flatten into the dot.
//
// Signal path:  BrownNoise → 7 × (BPF → BPF) at n·f0 (±detune) → × per-band swell, × shared grain envelope
//               + raw brown noise → FreeVerb → × fade env × master → ~pathosBus[\room] → R guard.
//
// Score words this patch reads (contract §4 "diagram patches may use or ignore"):
//   /pathos/diagram/position  level → a row of ~fate[\levels] (the glide between rows follows the lag)
//   /pathos/vial/chord        root → f0 (register low 55 / mid 110 / high 220 Hz) · brightness → spectral
//                             tilt of the seven harmonics · tension → how far the bands are pulled off the
//                             harmonics at fate and point (more conflict, slower to fuse) · density ignored
//   /pathos/state dwell       time dilation: every band narrows by ~fate[\dwellDilation]; narrower bands
//                             fluctuate more slowly (Δt ≈ 1/Δf), so the noise's own clock slows. Swells and
//                             grains slow with it.
//   ignores /pathos/vial/voices (the harmonic series is the harmony here)
//
// Test alone (after main.scd):  ~fateSweep.reset.play;  ~fateReleaseTest.reset.play;  ~fateTestStop.();
// Full scores with chair:      (sound/test/scores_fate-engage.scd).load  (see that file)
(
// ---- composer hooks -------------------------------------------------------------------------
~fate = ~fate ?? { () };
~fate[\amp] = 0.2;                    // patch gain before master and the room guard (≈ −30.5 LUFS; habit-build ≈ −33)
~fate[\fadeIn] = 5;                   // s, on start
~fate[\f0] = 110;                     // Hz, until the first /pathos/vial/chord (or always, if followRegister is false)
~fate[\followRegister] = true;        // f0 = chord root × registerMul
~fate[\registerMul] = 1;
~fate[\dwellDilation] = 0.5;          // in dwell: bandwidth × this, swells and grains slower by the same factor

// One row per level, fate (0) → point (1) → destiny (2). The synth glides between rows over the lag.
//   rq      reciprocal Q of each band (bandwidth / centre). Log-glided.
//   dry     raw brown noise (the field itself)        wet   the seven bands
//   detune  cents each band sits off its harmonic (odd below, even above), × (0.5 + tension)
//   common  0 = each band fluctuates on its own, 1 = all seven share one granular envelope (fused)
//   bloom   depth of each band's own slow swell        gain  loudness trim per row (measured, see notes)
~fate[\levels] = [
	(rq: 1.2,   dry: 1.0,  wet: 0.5, detune: 45, common: 0.0,  bloom: 0.7,  gain: 1.0),   // fate
	(rq: 0.045, dry: 0.22, wet: 1.0, detune: 14, common: 0.35, bloom: 0.45, gain: 1.0),   // point
	(rq: 0.006, dry: 0.04, wet: 1.0, detune: 0,  common: 0.85, bloom: 0.2,  gain: 1.0),   // destiny
];

// /pathos/vial/chord numbers → synth controls. Rewrite freely.
~fate[\fromChord] = { |root, density, brightness, tension|
	var e = (tilt: brightness.linlin(0.1, 0.9, 1.1, 0.25), tension: tension);   // amp of harmonic n ∝ n^-tilt
	if(~fate[\followRegister]) { e[\f0] = root * ~fate[\registerMul] };
	e
};

// ---- synth ----------------------------------------------------------------------------------
SynthDef(\fateVoice, { |out, masterBus, gate = 1, atk = 5, rel = 3, amp = 0.2, lag = 4,
		f0 = 110, rq = 1.2, dry = 1, wet = 0.5, detune = 45, tension = 0.5, common = 0, bloom = 0.7,
		tilt = 0.7, gain = 1, dil = 1, grainDur = 0.16, overlap = 4|
	var n     = (1..7);
	var signs = [-1, 1, -1, 1, -1, 1, -1];                    // odd harmonics converge from below, even from above
	var dilL  = VarLag.kr(dil, lag, warp: \sine);
	var f0L   = VarLag.kr(f0, lag, warp: \exp);
	var rqL   = VarLag.kr(rq.log, lag).exp * dilL;            // log glide: the funnel
	var detL  = VarLag.kr(detune * (0.5 + tension), lag);
	var fc    = f0L * n * (signs * detL / 100).midiratio;
	var src   = BrownNoise.ar;
	var bands = BPF.ar(BPF.ar(src, fc, rqL), fc, rqL);        // 4-pole: brown noise leaks a lot of low end
	var comp  = (fc / rqL).sqrt * 0.11;                       // brown noise: band power ∝ rq / fc
	var tiltL = VarLag.kr(tilt, lag);
	var shape = n.collect { |k| k.pow(tiltL.neg) };
	var swell = LFNoise2.kr({ ExpRand(0.05, 0.12) } ! 7 * dilL).range(1 - VarLag.kr(bloom, lag), 1);
	var harm  = (bands * comp * shape * swell).sum / shape.squared.sum.sqrt;
	var gd    = grainDur / dilL;
	var gt    = Dust.ar(overlap / gd);
	var genv  = GrainIn.ar(1, gt, gd * TExpRand.ar(0.7, 1.4, gt), DC.ar(1)) / (overlap * 0.5);
	var c     = VarLag.kr(common, lag);
	var env   = EnvGen.kr(Env.asr(atk, 1, rel, \sine), gate, doneAction: 2);
	var sig;
	harm = harm * (1 - c + (c * genv));                       // common fate
	sig  = (HPF.ar(src, 35) * 0.5 * VarLag.kr(dry, lag)) + (harm * VarLag.kr(wet, lag));
	sig  = FreeVerb.ar(sig * VarLag.kr(gain, lag), 0.3, 0.85, 0.5);
	sig  = Limiter.ar(sig * env * amp, 0.35, 0.02);         // rare noise bursts; the room guard stays the last resort
	Out.ar(out, sig * In.kr(masterBus, 1));
}).add;

// ---- state ----------------------------------------------------------------------------------
~fate[\level] = 0;

// ---- registry entry (called by diagrams.scd) ------------------------------------------------
~diagrams = ~diagrams ?? { () };
~diagrams[\fateEngage] = (
	start: {
		var f = ~fate, row = f[\levels][0];
		f[\stopNow].();
		f[\level] = 0; f[\dil] = 1;
		f[\synth] = Synth(\fateVoice, [
			out: ~pathosBus[\room], masterBus: ~pathosMasterBus, amp: f[\amp], atk: f[\fadeIn],
			f0: f[\f0], lag: ~pathosLag
		] ++ row.asKeyValuePairs, ~pathosGroup[\src]);
		"fate-engage: start".postln;
	},
	stop: { |rel = 3|
		var syn = ~fate[\synth];
		~fate[\synth] = nil;
		if(syn.notNil) {
			if(rel <= 0) { syn.free } { syn.set(\rel, rel, \gate, 0) };
			"fate-engage: stop (% s)".format(rel).postln;
		};
	},
	position: { |at, level, levels, depth|
		var rows = ~fate[\levels];
		var idx = level.linlin(0, (levels - 1).max(1), 0, rows.size - 1).round.asInteger;
		~fate[\level] = idx;
		~fate[\synth] !? { |x| x.set(\lag, ~pathosLag, *rows[idx].asKeyValuePairs) };
		"fate-engage: % (level % of %) → %".format(at, level, levels, rows[idx]).postln;
	},
);
~fate[\stopNow] = { ~diagrams[\fateEngage][\stop].value(0) };

// ---- extra score words (existing addresses; acts only while this diagram is active) -----------
OSCdef(\fateChord, { |m|
	if(~diagramActive == \fateEngage and: { ~fate[\synth].notNil }) {
		var e = ~fate[\fromChord].(m[1] ? 110, m[2] ? 0.5, m[3] ? 0.35, m[4] ? 0.5);
		~fate[\synth].set(\lag, ~pathosLag, *e.asKeyValuePairs);
		e[\f0] !? { |f| "fate-engage: f0 % Hz → harmonics %".format(f, (1..7) * f).postln };
	};
}, '/pathos/vial/chord');

OSCdef(\fateState, { |m|
	if(~diagramActive == \fateEngage and: { ~fate[\synth].notNil }
		and: { ~pathosSilentStates.includes(m[1]).not }) {
		~fate[\dil] = if(m[1] == \dwell) { ~fate[\dwellDilation] } { 1 };
		~fate[\synth].set(\lag, ~pathosLag, \dil, ~fate[\dil]);
	};
}, '/pathos/state');

if(~pathosLoading != true) { ~fate[\stopNow].() };             // re-evaluating this file mid-play

// ---- standalone tests (fake the orchestrator; run main.scd first) ---------------------------
// Each step: [phase, at, level, lag s, hold s]. Only select, lag, state and position are sent here:
// f0 stays at ~fate[\f0]. sound/test/scores_fate-engage.scd sends full movements (chord, chair).
~fateWalk = { |steps|
	Routine {
		var me = NetAddr.localAddr;
		~pathosFakeKeepalive.(true);
		me.sendMsg('/pathos/global/lag', 3);
		me.sendMsg('/pathos/global/master', 1.0);
		me.sendMsg('/pathos/diagram/select', "fate-engage");
		steps.do { |st|
			me.sendMsg('/pathos/global/lag', st[3]);
			me.sendMsg('/pathos/state', st[0]);
			me.sendMsg('/pathos/diagram/position', "fate-engage", st[1], st[2], 3, st[2] / 2);
			st[4].wait;
		};
		me.sendMsg('/pathos/global/lag', 6);
		me.sendMsg('/pathos/global/master', 0.0);
		me.sendMsg('/pathos/state', "idle");
		6.wait;
		~pathosFakeKeepalive.(false);
		"[fate] test done".postln;
	}
};
// Up the figure and back down: hold each level, then a slow glide to the next.
~fateSweep = ~fateWalk.([
	[\mirror, \fate, 0, 3, 20], [\transform, \point, 1, 10, 25], [\transform, \destiny, 2, 10, 30],
	[\transform, \point, 1, 10, 20], [\resurface, \fate, 0, 10, 20]]);
// The path of contract/examples/score_fate_engage_release.json (fate → point → destiny) with its lags:
// glide in, a cut into the point (and its dwell), then a slow glide out along the arrow.
~fateReleaseTest = ~fateWalk.([
	[\mirror, \fate, 0, 4, 30], [\dwell, \point, 1, 0.2, 30], [\resurface, \destiny, 2, 12, 45]]);
~fateTestStop = {
	[~fateSweep, ~fateReleaseTest].do(_.stop);
	~pathosFakeKeepalive.(false);
	NetAddr.localAddr.sendMsg('/pathos/state', "idle");
};
)
