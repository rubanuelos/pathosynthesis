(
s.options.numOutputBusChannels = 2;
~ch = (chair: 0, room: 1);            // L = bass shaker, R = 8" speaker

s.waitForBoot {
    ~chairBus = Bus.audio(s, 1);      // private buses; guards write to hardware
    ~roomBus  = Bus.audio(s, 1);
    ~srcGroup = Group.head(s);
    ~fxGroup  = Group.after(~srcGroup);
    s.sync;

SynthDef(\chanGuard, { |in, out, hpf = 20, maxAmp = 0.5|
    var sig = In.ar(in, 1);
    sig = LeakDC.ar(sig);
    sig = HPF.ar(HPF.ar(sig, hpf), hpf);     // 4th-order, protects transducers
    sig = Limiter.ar(sig, maxAmp, 0.01);     // ceiling = calibrated max
    Out.ar(out, sig);
}).add;

SynthDef(\idleChairPad, { |out, low = 41.203, high = 65.406, highAmp = 0.35,
                          amp = 0.4, lfoRate = 0.7, lfoDepth = 0.35,
                          glide = 1.5, atk = 6, rel = 6, gate = 1|
    var lowF  = Lag2.kr(low, glide);
    var lfo   = SinOsc.kr(lfoRate, 1.5pi).range(1 - lfoDepth, 1);   // starts at the trough
    var lowV  = SinOsc.ar(lowF + [0, 0.09]).sum * 0.5
              + (LPF.ar(LFTri.ar(lowF), lowF * 2.5) * 0.15);
    var highV = SinOsc.ar(high + [0, -0.07]).sum * 0.5 * highAmp;
    var env   = EnvGen.kr(Env.asr(atk, 1, rel, \sine), gate, doneAction: 2);
    Out.ar(out, (lowV + highV) * lfo * env * amp);
}).add;

/*SynthDef(\idleRoomTone, { |out, freq = 83, cents = 90, driftRate = 0.12, // This tone is kind of unnecessary
                          amp = 0.1, h2 = 0.2, atk = 6, rel = 6, gate = 1|
    var drift = LFNoise2.kr(driftRate).range(cents.neg, cents);
    var f     = freq * (drift / 100).midiratio;
    var sig   = SinOsc.ar(f) + (SinOsc.ar(f * 2) * h2);
    var env   = EnvGen.kr(Env.asr(atk, 1, rel, \sine), gate, doneAction: 2);
    Out.ar(out, sig * env * amp);
}).add;*/

SynthDef(\idleCrackle, { |out, density = 30, amp = 0.48, hiss = 0.004,
                         atk = 4, rel = 4, gate = 1|
    var trig  = Dust.ar(LFNoise1.kr(0.15).range(density * 0.3, density * 1.5));
    var a     = TRand.ar(0.0, 1.0, trig).squared;
    var dec   = TRand.ar(0.0003, 0.003, trig);
    var click = Decay2.ar(trig * a, 0.0001, dec) * WhiteNoise.ar;
    var sig   = BPF.ar(click, TRand.ar(2500, 7000, trig), 0.8) * 3
              + HPF.ar(PinkNoise.ar(hiss), 8000);
    var env   = EnvGen.kr(Env.asr(atk, 1, rel), gate, doneAction: 2);
    Out.ar(out, HPF.ar(sig, 1500) * env * amp);
}).add;

~idle = (freqs: [41.203, 36.708, 43], hold: 10);

~idleSeq = {
    Routine {
        var i = 0;
        loop {
            ~idlePad.set(\low, ~idle.freqs.wrapAt(i));
            ~idle.hold.wait;
            i = i + 1;
        }
    }
};

~idleStart = {
    if(~idleRunning != true) {
        ~idleRunning = true;
        ~guards = ~guards ?? {[
            Synth(\chanGuard, [in: ~chairBus, out: ~ch.chair, hpf: 20, maxAmp: 0.5], ~fxGroup),
            Synth(\chanGuard, [in: ~roomBus,  out: ~ch.room,  hpf: 30, maxAmp: 0.5], ~fxGroup)
        ]};
        ~idlePad   = Synth(\idleChairPad, [out: ~chairBus], ~srcGroup);
        // ~idleTone  = Synth(\idleRoomTone, [out: ~roomBus],  ~srcGroup);   // SynthDef commented out above
        ~idleCrack = Synth(\idleCrackle,  [out: ~roomBus],  ~srcGroup);
        ~idleRoutine = ~idleSeq.().play(SystemClock);
        "idle: on".postln;
    };
};

~idleStop = { |rel = 4|
    if(~idleRunning == true) {
        ~idleRunning = false;
        ~idleRoutine.stop;
        [~idlePad, ~idleTone, ~idleCrack].do(_.set(\rel, rel, \gate, 0));
        "idle: off".postln;
    };
};

// FOLLOWS ORCHESTRATOR'S STATE
OSCdef(\idleState, { |msg|
    if(msg[1] == \idle) { ~idleStart.() } { ~idleStop.(3) };
}, '/pathos/state');

OSCdef(\idlePanic, { ~idleStop.(0.5) }, '/pathos/panic');

"idle: server ready".postln;
};
)

/* Test tail (select a line and evaluate in the IDE; never runs on load):
s.meter;
s.scope(2);

~idleStart.();
~idleStop.();

n = NetAddr.localAddr; n.sendMsg('/pathos/state', \idle);
n.sendMsg('/pathos/state', \mirror); // fade out
*/


