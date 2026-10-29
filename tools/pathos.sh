#!/usr/bin/env bash
# tools/pathos.sh — start the whole installation from one terminal (node 00, integration glue).
#
#   tools/pathos.sh            SuperCollider (sound/main.scd, incl. idle) → voice → orchestrator
#
# Then, in this terminal: s start a session · x abort · p / SPACE panic · Ctrl-C panic + quit.
# On quit it stops the voice node and SuperCollider. Logs: orchestrator/logs/{sc,voice}.log
# (gitignored, local only, contract §7.5).
#
# Quit the SuperCollider IDE first: if its interpreter holds port 57120, this sclang gets
# another port and the orchestrator would be talking to the IDE. The script refuses in that case.
# Override the sclang path with SCLANG=/path/to/sclang tools/pathos.sh

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
SCLANG="${SCLANG:-/Applications/SuperCollider.app/Contents/MacOS/sclang}"
LOGS="$ROOT/orchestrator/logs"
mkdir -p "$LOGS"

[ -f .venv/bin/activate ] && . .venv/bin/activate
[ -x "$SCLANG" ] || { echo "pathos: sclang not found at $SCLANG (set SCLANG=...)"; exit 1; }
[ -n "$ANTHROPIC_API_KEY" ] || grep -q "^ANTHROPIC_API_KEY=." .env 2>/dev/null || echo "pathos: WARNING no ANTHROPIC_API_KEY (shell or .env): interpretation will fail and fallbacks will play"

SC_PID=""; VOICE_PID=""; FIFO=""
cleanup() {
    echo; echo "pathos: stopping voice and SuperCollider…"
    [ -n "$VOICE_PID" ] && kill "$VOICE_PID" 2>/dev/null
    [ -n "$SC_PID" ] && kill "$SC_PID" 2>/dev/null
    exec 3>&- 2>/dev/null
    [ -n "$FIFO" ] && rm -f "$FIFO"
    sleep 1
    pkill -x scsynth 2>/dev/null   # the server sclang booted; one installation per machine
    echo "pathos: stopped."
}
trap cleanup EXIT
trap 'exit 130' INT TERM

wait_for() {  # wait_for <seconds> <description> <command...>; the command returning 2 means "give up now"
    local t=$1 what=$2 rc; shift 2
    for _ in $(seq 1 $((t * 2))); do
        "$@" >/dev/null 2>&1; rc=$?
        [ $rc -eq 0 ] && return 0
        [ $rc -eq 2 ] && { echo "pathos: $what: process exited"; return 1; }
        sleep 0.5
    done
    echo "pathos: timed out after ${t}s waiting for $what"; return 1
}

# 0. Nothing else may hold the voice port: a stale voice node would answer /health and fail every /ask.
STALE=$(lsof -nP -iTCP:8010 -sTCP:LISTEN -t 2>/dev/null)
if [ -n "$STALE" ]; then
    echo "pathos: port 8010 is already in use (an old voice node?):"
    ps -o pid=,command= -p $STALE
    echo "pathos: stop it with:  kill $STALE   then run tools/pathos.sh again"
    exit 1
fi

# 1. SuperCollider. sclang reads its stdin from a FIFO this script holds open on fd 3, so it keeps
#    running in the background and gets EOF when the script ends.
: > "$LOGS/sc.log"
FIFO="$(mktemp -u "${TMPDIR:-/tmp}/pathos-sclang.XXXXXX")"
mkfifo "$FIFO" || exit 1
"$SCLANG" sound/main.scd < "$FIFO" >> "$LOGS/sc.log" 2>&1 &
SC_PID=$!
exec 3> "$FIFO"
echo "pathos: SuperCollider booting (log: orchestrator/logs/sc.log)…"
wait_for 60 "SuperCollider READY" grep -q "\[pathos\] READY" "$LOGS/sc.log" || exit 1
grep -q "\[pathos\] READY on port 57120" "$LOGS/sc.log" || {
    echo "pathos: sclang is not on port 57120 (is the SC IDE open?):"; grep "\[pathos\] READY" "$LOGS/sc.log"; exit 1; }
grep -qi "idle: server ready" "$LOGS/sc.log" || echo "pathos: WARNING idle.scd did not report ready (see sc.log)"

# 2. Voice node (Whisper takes a few seconds to load).
python -m voice.serve > "$LOGS/voice.log" 2>&1 < /dev/null &
VOICE_PID=$!
echo "pathos: voice node starting (log: orchestrator/logs/voice.log)…"
voice_up() { kill -0 "$VOICE_PID" 2>/dev/null || return 2; curl -sf http://127.0.0.1:8010/health; }
wait_for 120 "voice /health" voice_up || { echo "pathos: voice node failed:"; tail -5 "$LOGS/voice.log"; exit 1; }

# 3. Orchestrator in the foreground: it owns the keys. Its startup sends /pathos/state idle → idle plays.
echo "pathos: all up. Idle is playing. Press s to start a session."
python -m orchestrator.run
