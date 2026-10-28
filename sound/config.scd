// sound/config.scd — shared plumbing for node 02 (contract v0.3 §1.1, §4, §7).
// Loaded by sound/main.scd. This file only defines values and functions; ~pathosSetup does the
// server work and must run inside a Routine on a booted server (main.scd does that).
//
// Signal path (everything private until the guards):
//   diagram patch → its own stereo bus → sum to mono × master → ~pathosBus[\room] ─→ \chanGuard → out 1 (R, speaker)
//   chair layer   → ~pathosBus[\chairPre] → × master (\pathosGain) → ~pathosBus[\chair] → \chanGuard → out 0 (L, shaker)
//
// Coexists with idle.scd: every global here starts with ~pathos. idle.scd owns ~ch, ~chairBus, ~roomBus,
// ~srcGroup, ~fxGroup, ~guards and ~idle*, and its own guards; nothing here touches them. idle.scd is not
// scaled by master (contract §5.1).
(
// ---- install constants ----------------------------------------------------------------------
~pathosCh  = (chair: 0, room: 1);   // L = bass shaker, R = 8" speaker. Must equal idle.scd's ~ch.
~pathosCal = (chairMax: 0.5, chairHpf: 20, roomMax: 0.5, roomHpf: 30); // guard ceilings + HPFs, same as idle's guards. Set at install.
~pathosWatchdog = (timeout: 5, fade: 3); // s: no /pathos/keepalive for `timeout` → master to 0 over `fade`
~pathosPanicFade = 0.5;                  // s: /pathos/panic → silence
~pathosSilentStates = [\idle, \asking, \composing]; // diagram patch and chair layer are silent in these
~pathosStates = [\idle, \asking, \composing, \mirror, \dwell, \transform, \resurface];

~pathosServerOptions = {
	s.options.numOutputBusChannels = 2;
	// s.options.outDevice = "Your Interface Name";   // exact name from ServerOptions.outDevices
};

// ---- setup (inside a Routine, server booted) --------------------------------------------------
~pathosSetup = {
	var cal = ~pathosCal, wd = ~pathosWatchdog;
	~pathosTeardown.();

	if(~ch.notNil and: { ~ch[\chair] != ~pathosCh[\chair] or: { ~ch[\room] != ~pathosCh[\room] } }) {
		"pathos: ~pathosCh % differs from idle.scd's ~ch % — fix one of them".format(~pathosCh, ~ch).warn;
	};

	// Byte-identical to idle.scd's \chanGuard, so loading either file first gives the same guard.
	// If you change one, change both (or rename this one).
	SynthDef(\chanGuard, { |in, out, hpf = 20, maxAmp = 0.5|
	    var sig = In.ar(in, 1);
	    sig = LeakDC.ar(sig);
	    sig = HPF.ar(HPF.ar(sig, hpf), hpf);     // 4th-order, protects transducers
	    sig = Limiter.ar(sig, maxAmp, 0.01);     // ceiling = calibrated max
	    Out.ar(out, sig);
	}).add;

	// Master as a control signal: target (with lag) × watchdog gate (linear `fade` s both ways).
	SynthDef(\pathosMasterCtl, { |out, amp = 1, lag = 3, alive = 1|
		Out.kr(out, Lag.kr(amp, lag) * Slew.kr(alive, 1 / wd[\fade], 1 / wd[\fade]));
	}).add;

	// Mono gain stage: in × master → out. Used by the chair layer.
	SynthDef(\pathosGain, { |in, out, masterBus|
		Out.ar(out, In.ar(in, 1) * In.kr(masterBus, 1));
	}).add;

	s.sync;

	~pathosBus = (
		chairPre: Bus.audio(s, 1),   // chair layer writes here
		chair:    Bus.audio(s, 1),   // after master, into the chair guard
		room:     Bus.audio(s, 1),   // diagram patches write their mono sum here (already × master)
	);
	~pathosMasterBus = Bus.control(s, 1);

	// ctl → src → fx → guard, at the tail of the default group (idle.scd's groups sit at the head).
	~pathosGroup = ();
	~pathosGroup[\ctl]   = Group.tail(s);
	~pathosGroup[\src]   = Group.after(~pathosGroup[\ctl]);
	~pathosGroup[\fx]    = Group.after(~pathosGroup[\src]);
	~pathosGroup[\guard] = Group.after(~pathosGroup[\fx]);

	~pathosLag = 4;     // current /pathos/global/lag
	~pathosMaster = 1;  // current /pathos/global/master target
	~pathosAlive = true;
	~pathosLastKeepalive = Main.elapsedTime;

	~pathosMasterSynth = Synth(\pathosMasterCtl,
		[out: ~pathosMasterBus, amp: ~pathosMaster], ~pathosGroup[\ctl]);
	~pathosChairGain = Synth(\pathosGain,
		[in: ~pathosBus[\chairPre], out: ~pathosBus[\chair], masterBus: ~pathosMasterBus], ~pathosGroup[\fx]);
	~pathosGuards = [
		Synth(\chanGuard, [in: ~pathosBus[\chair], out: ~pathosCh[\chair], hpf: cal[\chairHpf], maxAmp: cal[\chairMax]], ~pathosGroup[\guard]),
		Synth(\chanGuard, [in: ~pathosBus[\room],  out: ~pathosCh[\room],  hpf: cal[\roomHpf],  maxAmp: cal[\roomMax]],  ~pathosGroup[\guard]),
	];

	// ---- global OSC (contract §4) ----
	OSCdef(\pathosState, { |m|
		if(~pathosStates.includes(m[1])) { "[pathos] state: %".format(m[1]).postln }
		{ "[pathos] unknown state '%' (v0.3: %)".format(m[1], ~pathosStates).warn };
	}, '/pathos/state');

	OSCdef(\pathosLag, { |m| ~pathosLag = (m[1] ? ~pathosLag).clip(0, 30) }, '/pathos/global/lag');

	OSCdef(\pathosMaster, { |m|
		~pathosMaster = (m[1] ? ~pathosMaster).clip(0, 1);
		~pathosMasterSynth.set(\lag, ~pathosLag.max(0.05), \amp, ~pathosMaster);
	}, '/pathos/global/master');

	OSCdef(\pathosKeepalive, {
		~pathosLastKeepalive = Main.elapsedTime;
		if(~pathosAlive.not) {
			~pathosAlive = true;
			~pathosMasterSynth.set(\alive, 1);
			"[pathos] keepalive back — master restored over % s".format(wd[\fade]).postln;
		};
	}, '/pathos/keepalive');

	// Panic: master to 0 in 0.5 s. diagrams.scd and the chair layer stop/zero themselves too.
	// Not latched: the orchestrator's next /pathos/global/master brings master back.
	OSCdef(\pathosPanic, {
		~pathosMaster = 0;
		~pathosMasterSynth.set(\lag, ~pathosPanicFade, \amp, 0);
		"[pathos] PANIC — master to 0 in % s".format(~pathosPanicFade).warn;
	}, '/pathos/panic');

	~pathosWatchdogRoutine = Routine {
		loop {
			0.25.wait;
			if(~pathosAlive and: { Main.elapsedTime - ~pathosLastKeepalive > wd[\timeout] }) {
				~pathosAlive = false;
				~pathosMasterSynth.set(\alive, 0);
				"[pathos] WATCHDOG — no /pathos/keepalive for % s, master to 0 over % s".format(wd[\timeout], wd[\fade]).warn;
			};
		}
	}.play(SystemClock);

	~pathosReady = true;
	"[pathos] config: outs %, guards chair % / room %".format(~pathosCh, cal[\chairMax], cal[\roomMax]).postln;
};

// Frees everything config.scd made (and stops diagram patches). Never touches idle.scd's nodes.
~pathosTeardown = {
	if(~pathosReady == true) {
		~diagrams !? { |d| d.do { |e| e[\stop].value(0) } };
		~diagramActive = nil;
		~pathosWatchdogRoutine.stop;
		~pathosFakeKeepalive.(false);
		~pathosGroup.do(_.free);
		~pathosBus.do(_.free);
		~pathosMasterBus.free;
		~pathosReady = false;
		"[pathos] previous instance torn down".postln;
	};
};

// For testing without the orchestrator: ~pathosFakeKeepalive.(true) / .(false). Sends 4 Hz to ourselves.
~pathosFakeKeepalive = { |on = true|
	~pathosFakeKA !? { |r| r.stop };
	~pathosFakeKA = nil;
	if(on) {
		~pathosFakeKA = Routine {
			var n = NetAddr("127.0.0.1", NetAddr.langPort);
			loop { n.sendMsg('/pathos/keepalive'); 0.25.wait };
		}.play(SystemClock);
	};
};
)
