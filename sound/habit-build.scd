// sound/habit-build.scd — habit-build patch, wired into the diagram registry (contract v0.3 §4).
// Loaded by main.scd after diagrams.scd. Your original composition is unchanged in _pre-v03/habit-build.scd;
// the material below (transposeArray, delayArray, scale, sequence, durs, the \clip voice, comb + verb)
// is the same, only re-routed and made start/stop/position-able.
//
// Signal path:  \habitClip notes → ~habit[\bus] (private stereo)
//               → \habitFx (comb + verb + dry, sum to mono, × fade env × master) → ~pathosBus[\room] → R guard
// Nothing here writes to a hardware bus, so the room guard, master, watchdog and panic all apply.
//
// Positions (contract/diagrams.json, nested circles): intention 0 (innermost) · action 1 · behavior 2 ·
// habit 3 · nature 4 (outermost). Inward = fewer pitches, outward = more: see ~habit[\pitchesPerLevel].
//
// Test alone (after main.scd):  ~habitTest.reset.play;   ~habitDissolveTest.reset.play;   ~habitTestStop.();
(
var transposeArray = [ 0, 0, 6, 6, 8, 9, 12, 12, 15, 18, 18, 21, 24, 27, 29, 32];
var delayArray =     [ 1.125, 1.25, 1.5, 2, 2, 2.125, 2.25, 3, 3, 4, 6.5 ];
var scale = Array.fill(7, {|i| Scale.todi.degrees+(i*8)}).flatten+24;
var sequence = [0, 2, 5, 3, 4, 1, 2, 5, 0];
var durs     = [1, 1, 2, 1, 1, 3, 2, 1, 2] / 4;
var order    = sequence.inject([], { |acc, d| if(acc.includes(d)) { acc } { acc ++ [d] } }); // [0, 2, 5, 3, 4, 1]

// ---- composer hooks -------------------------------------------------------------------------
~habit = ~habit ?? { () };
~habit[\amp] = 0.8;                         // patch gain before master and the room guard
~habit[\fadeIn] = 4;                        // s, on start
// Distinct pitches allowed at each level, innermost → outermost. Index = level (0..levels-1).
// The phrase keeps its rhythm: notes outside the allowed set become rests.
~habit[\pitchesPerLevel] = [1, 2, 3, 4, 6];

// Returns [notes, durs, restMask] for a level. Rewrite freely: this is where a level becomes sound.
~habit[\phraseFor] = { |level, levels|
	var table = ~habit[\pitchesPerLevel];
	var idx = level.linlin(0, (levels - 1).max(1), 0, table.size - 1).round.asInteger;
	var allowed = order.keep(table[idx]);
	var play = sequence.collect { |d| allowed.includes(d) };
	[sequence, durs, play]
};

// ---- synths ---------------------------------------------------------------------------------
SynthDef(\habitClip, { |out, freq, pan, amp|
	var signal = SinOsc.ar(freq, pi/36, amp);
	var lfo = SinOsc.ar(10).range(0.05, 0.2);
	var env = EnvGen.ar(Env.perc(0.0, 1, 1, -10.0), doneAction: 2);
	Out.ar(out, Pan2.ar(signal * lfo * env, pan));
}).add;

// The two `{ }.play` effects from the original, now reading the patch's own bus instead of hardware out 0.
SynthDef(\habitFx, { |in, out, masterBus, amp = 0.8, gate = 1, atk = 4, rel = 3|
	var dry  = In.ar(in, 2);
	var comb = LPF.ar(CombC.ar(dry, 0.5, 0.375, 2), 2000) * 0.25;
	var verb = LPF.ar(FreeVerb.ar(dry, 3), 1000) * 0.05;   // as in the original: FreeVerb mix arg = 3 (clipped to 1)
	var env  = EnvGen.kr(Env.asr(atk, 1, rel, \sine), gate, doneAction: 2);
	var sig  = (dry + comb + verb).sum;                   // stereo → mono for the single R speaker
	Out.ar(out, sig * env * amp * In.kr(masterBus, 1));
}).add;

// ---- state ----------------------------------------------------------------------------------
~habit[\level] = 4;
~habit[\levels] = 5;
~habit[\run] = false;

// One phrase, as in the original: a fixed transposition and pan, repeated 4–10 times.
~habit[\phraseRoutine] = { |pan, transpose|
	var amp = transpose.linlin(0, 32, 0, -18).dbamp;
	Routine {
		rrand(4, 10).do {
			// Re-read the level each repetition, so a position change is heard within one phrase.
			var p = ~habit[\phraseFor].(~habit[\level], ~habit[\levels]);
			var notes = p[0] + transpose, ds = p[1], mask = p[2];
			if(~habit[\run].not) { nil.alwaysYield };
			notes.size.do { |i|
				if(mask[i] and: { ~habit[\run] }) {
					s.bind { Synth(\habitClip, [\out, ~habit[\bus], \freq, scale[notes[i]].midicps, \pan, pan, \amp, amp], ~habit[\group]) };
				};
				ds[i].wait;
			};
		};
	}
};

// ---- registry entry (called by diagrams.scd) ------------------------------------------------
~diagrams = ~diagrams ?? { () };
~diagrams[\habitBuild] = (
	start: {
		~habit[\stopNow].();                                   // clean slate if re-selected
		~habit[\bus] = Bus.audio(s, 2);
		~habit[\group] = Group.tail(~pathosGroup[\src]);
		~habit[\fx] = Synth(\habitFx, [in: ~habit[\bus], out: ~pathosBus[\room], masterBus: ~pathosMasterBus,
			amp: ~habit[\amp], atk: ~habit[\fadeIn]], ~pathosGroup[\fx]);
		~habit[\level] = ~habit[\levels] - 1;                  // outermost until the first position arrives
		~habit[\transpose] = 12;
		~habit[\run] = true;
		~habit[\main] = Routine {
			1.wait;
			while { ~habit[\run] } {
				~habit[\phraseRoutine].(rrand(-1.0, 1), ~habit[\transpose]).play;
				~habit[\transpose] = transposeArray.choose;
				delayArray.choose.wait;
			};
		}.play;
		"habit-build: start".postln;
	},
	stop: { |rel = 3|
		var fx = ~habit[\fx], grp = ~habit[\group], bus = ~habit[\bus];
		~habit[\run] = false;
		~habit[\main] !? { |r| r.stop };
		~habit[\main] = nil; ~habit[\fx] = nil; ~habit[\group] = nil; ~habit[\bus] = nil;
		if(fx.notNil) {
			if(rel <= 0) { fx.free; grp.free; bus.free } {
				fx.set(\rel, rel, \gate, 0);
				SystemClock.sched(rel + 0.5, { grp.free; bus.free; nil });
			};
			"habit-build: stop (% s)".format(rel).postln;
		};
	},
	position: { |at, level, levels, depth|
		~habit[\levels] = levels.max(1);
		~habit[\level] = level.clip(0, ~habit[\levels] - 1);
		"habit-build: % (level % of %) → % pitches".format(at, level, levels,
			~habit[\phraseFor].(~habit[\level], ~habit[\levels]).at([0, 2]).flop
				.select(_[1]).collect(_[0]).asSet.size).postln;
	},
);
~habit[\stopNow] = { ~diagrams[\habitBuild][\stop].value(0) };
if(~pathosLoading != true) { ~habit[\stopNow].() };            // re-evaluating this file mid-play

// ---- standalone tests (fake the orchestrator; run main.scd first) ---------------------------
~habitWalk = { |steps, step = 20|
	Routine {
		var me = NetAddr.localAddr;
		~pathosFakeKeepalive.(true);
		me.sendMsg('/pathos/global/lag', 3);
		me.sendMsg('/pathos/global/master', 1.0);
		me.sendMsg('/pathos/diagram/select', "habit-build");
		steps.do { |st|
			me.sendMsg('/pathos/state', st[0]);
			me.sendMsg('/pathos/diagram/position', "habit-build", st[1], st[2], 5, st[2] / 4);
			step.wait;
		};
		me.sendMsg('/pathos/state', "idle");
		4.wait;
		~pathosFakeKeepalive.(false);
		"[habit] test done".postln;
	}
};
// outer → inner → back out (hear the pitch count shrink, then grow)
~habitTest = ~habitWalk.([[\mirror, "nature", 4], [\dwell, "habit", 3], [\transform, "behavior", 2],
	[\transform, "action", 1], [\transform, "intention", 0], [\resurface, "nature", 4]], 15);
// same path as contract/examples/score_habit_build_dissolve.json
~habitDissolveTest = ~habitWalk.([[\mirror, "nature", 4], [\dwell, "habit", 3],
	[\transform, "action", 1], [\resurface, "intention", 0]], 15);
~habitTestStop = { ~habitTest.stop; ~habitDissolveTest.stop; NetAddr.localAddr.sendMsg('/pathos/state', "idle") };
)
