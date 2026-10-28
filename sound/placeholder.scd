// sound/placeholder.scd — the chair layer (contract v0.3 §1.1: L = bass shaker), independent of the diagram patch.
// Loaded by sound/main.scd. \pathosHeart and \pathosDrone are unchanged from the v0.1 placeholder.
//
// Changes from v0.1:
//   - heart and drone write to ~pathosBus[\chairPre] → × master → chair \chanGuard → out 0 (was hardware out 2)
//   - the 4-out map is gone (config.scd: chair 0, room 1)
//   - the \pathosVial pad is gone: the R channel is the diagram patch now, and SC must be silent on R
//     during asking/composing. Nobody listens to /pathos/vial/* (diagram patches may use or ignore them).
//   - master is applied as a signal (config.scd) so the watchdog can fade it, not multiplied in at set time
//   - OSCdef keys are \pathosChair…; the chair goes to 0 in idle/asking/composing; states are v0.3
(
SynthDef(\pathosHeart, { |out=2, bpm=66, irregularity=0, intensity=0.6, lag=4, maxAmp=0.6|
    var rate = bpm.lag(lag) / 60;
    var jitter = LFNoise1.kr(rate * 2).range(1 - irregularity.lag(lag), 1 + irregularity.lag(lag));
    var trig = Impulse.kr(rate * jitter);
    var dub = TDelay.kr(trig, (0.28 / rate.max(0.5)).min(0.3));
    var env = EnvGen.ar(Env.perc(0.005, 0.18), trig) + (EnvGen.ar(Env.perc(0.005, 0.14), dub) * 0.6);
    var sig = SinOsc.ar(48 + (env * 20)) * env;   // pitch drops slightly through each thump
    sig = HPF.ar(sig, 20) * intensity.lag(lag);
    Out.ar(out, Limiter.ar(sig, maxAmp));
}).add;

SynthDef(\pathosDrone, { |out=2, freq=40, amp=0.0, lag=4, maxAmp=0.6|
    var sig = SinOsc.ar(freq.lag(lag)) * amp.lag(lag);
    Out.ar(out, Limiter.ar(HPF.ar(sig, 20), maxAmp * 0.6));
}).add;

~chairMaxAmp = 0.6;   // the layer's own limiter, as before. The output ceiling is ~pathosCal[\chairMax] (guard).
if(~pathosLoading == true) { ~chairHeart = nil; ~chairDrone = nil };   // main.scd's teardown already freed them

~chairStart = {
	[~chairHeart, ~chairDrone].do { |x| x !? { x.free } };
	~chairHeart = Synth(\pathosHeart, [\out, ~pathosBus[\chairPre], \maxAmp, ~chairMaxAmp, \intensity, 0], ~pathosGroup[\src]);
	~chairDrone = Synth(\pathosDrone, [\out, ~pathosBus[\chairPre], \maxAmp, ~chairMaxAmp], ~pathosGroup[\src]);
	"[pathos] chair layer on (out %)".format(~pathosCh[\chair]).postln;
};
~chairZero = { |lag|
	~chairHeart.set(\lag, lag, \intensity, 0);
	~chairDrone.set(\lag, lag, \amp, 0);
};

// ---------- OSC (contract §4) ----------
OSCdef(\pathosChairHeart, { |m|
    ~chairHeart.set(\lag, ~pathosLag, \bpm, m[1].clip(40, 110), \irregularity, m[2].clip(0, 1),
        \intensity, m[3].clip(0, 1));
}, '/pathos/chair/heartbeat');
OSCdef(\pathosChairDrone, { |m|
    ~chairDrone.set(\lag, ~pathosLag, \freq, m[1].clip(25, 80), \amp, m[2].clip(0, 1));
}, '/pathos/chair/drone');
OSCdef(\pathosChairState, { |m|
	if(~pathosSilentStates.includes(m[1])) { ~chairZero.(~pathosLag) };
}, '/pathos/state');
OSCdef(\pathosChairPanic, { ~chairZero.(~pathosPanicFade) }, '/pathos/panic');

// ---------- standalone test (fakes the orchestrator) ----------
// ~testSequence.reset.play;
~testSequence = Routine {
    var me = NetAddr.localAddr;
    ~pathosFakeKeepalive.(true);
    me.sendMsg('/pathos/global/lag', 4);
    me.sendMsg('/pathos/state', "mirror");
    me.sendMsg('/pathos/chair/heartbeat', 84, 0.35, 0.9);
    me.sendMsg('/pathos/chair/drone', 35, 0.3);
    12.wait;
    me.sendMsg('/pathos/global/lag', 0.2);
    me.sendMsg('/pathos/state', "dwell");
    me.sendMsg('/pathos/chair/heartbeat', 56, 0, 0.6);
    8.wait;
    me.sendMsg('/pathos/global/lag', 12);
    me.sendMsg('/pathos/state', "transform");
    me.sendMsg('/pathos/chair/heartbeat', 48, 0, 0.3);
    me.sendMsg('/pathos/chair/drone', 30, 0.1);
    20.wait;
    me.sendMsg('/pathos/state', "idle");
    ~pathosFakeKeepalive.(false);
    "[pathos] test sequence done".postln;
};

// Evaluated on its own (not from main.scd): restart the chair synths with the new definitions.
if(~pathosLoading != true) {
	if(~pathosReady == true) { fork { s.sync; ~chairStart.() } } { "placeholder: run sound/main.scd first".warn };
};
)
