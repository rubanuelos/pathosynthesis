// sound/main.scd — loads node 02 in order. Evaluate the block in the IDE, or: sclang sound/main.scd
// Re-evaluating is safe: config.scd tears down its previous instance first (idle.scd is never touched).
//
//   config.scd          channel map, private buses, groups, guards, master, watchdog, global OSC
//   diagrams.scd        registry ~diagrams + /pathos/diagram/select and /position dispatch
//   placeholder.scd     chair layer (\pathosHeart, \pathosDrone, /pathos/chair/*)
//   habit-build.scd     habit-build patch    fate-engage.scd, mystery-engage.scd   stubs
//
// idle.scd is loaded separately, the way you run it now (it doesn't parse as one file yet: see
// the notes in the 02 chat). Once it does, uncomment the line below.
(
var dir = thisProcess.nowExecutingPath.dirname;
(dir +/+ "config.scd").load;
~pathosServerOptions.();

s.waitForBoot {
	~pathosLoading = true;
	~pathosSetup.();
	(dir +/+ "diagrams.scd").load;
	(dir +/+ "placeholder.scd").load;
	(dir +/+ "habit-build.scd").load;
	(dir +/+ "fate-engage.scd").load;
	(dir +/+ "mystery-engage.scd").load;
	s.sync;
	~chairStart.();
	// (dir +/+ "idle.scd").load;
	~pathosLoading = false;
	"\n[pathos] READY on port %. Try ~habitTest.reset.play or ~habitDissolveTest.reset.play\n".format(NetAddr.langPort).postln;
};
)
