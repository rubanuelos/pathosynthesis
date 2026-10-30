// sound/main.scd — loads node 02 in order. Evaluate the block in the IDE, or: sclang sound/main.scd
// (tools/pathos.sh runs it headless). Re-evaluating is safe: config.scd tears down its previous
// instance first, and idle.scd's previous nodes are freed before it loads again.
//
//   config.scd          channel map, private buses, groups, guards, master, watchdog, global OSC
//   diagrams.scd        registry ~diagrams + /pathos/diagram/select and /position dispatch
//   placeholder.scd     chair layer (\pathosHeart, \pathosDrone, /pathos/chair/*)
//   habit-build.scd     habit-build patch
//   fate-engage.scd     fate-engage patch: brown noise filtered into 7 JI harmonics (sound/docs/diagram_translations.md)
//   mystery-engage.scd  mystery-engage patch: 5 granular vertex pitches within 90 cents, lines = beatings
//   sound/test/scores_<diagram>.scd   full mapped scores with the chair layer (not loaded here; evaluate on demand)
//   idle.scd            idle soundscape. Silent until the orchestrator sends /pathos/state idle.
(
var dir = thisProcess.nowExecutingPath.dirname;
(dir +/+ "config.scd").load;
~pathosServerOptions.();

s.waitForBoot {
	var t0;
	~pathosLoading = true;
	~pathosSetup.();
	(dir +/+ "diagrams.scd").load;
	(dir +/+ "placeholder.scd").load;
	(dir +/+ "habit-build.scd").load;
	(dir +/+ "fate-engage.scd").load;
	(dir +/+ "mystery-engage.scd").load;
	s.sync;
	~chairStart.();

	// idle.scd keeps its own buses, groups and guards. On a re-run, free the previous ones first:
	// its `~guards ?? {…}` would otherwise keep guards that read the old buses (idle would go silent).
	[~srcGroup, ~fxGroup].do { |g| g !? { g.free } };
	[~chairBus, ~roomBus].do { |b| b !? { b.free } };
	~idleRoutine !? { |r| r.stop };
	~guards = nil; ~idleRunning = false; ~idleStart = nil;
	(dir +/+ "idle.scd").load;
	// idle.scd's waitForBoot body runs a moment later (on AppClock); wait for it, so
	// "idle: server ready" is posted before READY.
	t0 = Main.elapsedTime;
	while { ~idleStart.isNil and: { Main.elapsedTime - t0 < 10 } } { 0.05.wait };
	if(~idleStart.isNil) { "[pathos] idle.scd did not finish loading".warn };
	s.sync;

	~pathosLoading = false;
	"\n[pathos] READY on port %. Try ~habitTest.reset.play · ~fateSweep.reset.play · ~mysteryTour.reset.play\n".format(NetAddr.langPort).postln;
};
)
