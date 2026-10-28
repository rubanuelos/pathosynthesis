"""voice/serve.py — HTTP front of node 06 (contract §2.4).

    python -m voice.serve                       real audio (TTS on R, mic, Whisper)
    python -m voice.serve --fake                answers typed on the keyboard
    python -m voice.serve --fake --script a.txt answers read from a file, one per line
    python -m voice.serve --fake --speak        keyboard answers, questions spoken for real

Endpoints
    POST /ask   {"text", "lang"?, "listen_max_s"?=45, "end_silence_s"?=2.5}
                200 {"answer", "status": ok|silence|timeout, "speech_s", "lang"}
                400 {"error"}  bad body
                409 {"error": "stopped"}  cut by /stop or by a newer /ask
                500 {"error"}  device or engine failure (orchestrator falls back)
    POST /stop  200 {"ok": true}   (idempotent)
    GET  /health 200 {"ok": true}  | 503 {"ok": false}

Stdlib HTTP server: one thread per request, so /stop lands while /ask blocks.
Body is parsed as JSON whatever the content-type (so bare `curl -d` works).
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config as config_mod
from .engine import AskRequest, BadRequest, FakeEngine, Stopped, VoiceService

log = logging.getLogger("voice")
MAX_BODY = 64 * 1024


def make_handler(service: VoiceService, cfg: config_mod.Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"pathos-voice/{config_mod.CONTRACT_VERSION}"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # route http.server chatter to logging
            log.debug("http %s", fmt % args)

        def _json(self, code: int, obj: dict) -> None:
            data = json.dumps(obj, ensure_ascii=False).encode()
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                log.warning("client went away before the %s response", code)

        def _body(self) -> object:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise BadRequest("body too large")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                return json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BadRequest(f"invalid JSON: {exc}") from exc

        def do_GET(self):
            if self.path.rstrip("/") == "/health":
                ok = service.ready()
                self._json(200 if ok else 503, {"ok": ok})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.rstrip("/")
            if path == "/stop":
                try:
                    self._body()  # drain, ignore
                except BadRequest:
                    pass
                was = service.stop()
                log.info("/stop (%s)", "cut a running ask" if was else "nothing running")
                self._json(200, {"ok": True})
                return
            if path != "/ask":
                self._json(404, {"error": "not found"})
                return
            try:
                req = AskRequest.parse(self._body(), cfg)
            except BadRequest as exc:
                self._json(400, {"error": str(exc)})
                return
            try:
                res = service.ask(req)
            except Stopped:
                self._json(409, {"error": "stopped"})
                return
            except Exception as exc:  # device unplugged, TTS missing, ...
                log.exception("/ask failed")
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
                return
            self._json(200, res)

    return Handler


def build_server(service: VoiceService, cfg: config_mod.Config,
                 host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host or cfg.server.host, cfg.server.port if port is None else port),
                              make_handler(service, cfg))
    srv.daemon_threads = True
    return srv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m voice.serve", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="TOML config (default: voice/config.toml)")
    ap.add_argument("--port", type=int)
    ap.add_argument("--fake", action="store_true", help="keyboard answers instead of the mic")
    ap.add_argument("--script", help="with --fake: file of answers, one per line")
    ap.add_argument("--fake-delay", type=float, default=0.5, help="with --script: seconds per answer")
    ap.add_argument("--speak", action="store_true", help="with --fake: speak questions with real TTS")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    cfg = config_mod.load(args.config)

    if args.fake:
        tts = None
        if args.speak:
            from . import audio, tts as tts_mod
            audio.check_output_routing(cfg.output)
            tts = tts_mod.make(cfg.tts, cfg.output)
        script = None
        if args.script:
            script = Path(args.script).read_text(encoding="utf-8").splitlines()
        engine = FakeEngine(cfg, script=script, delay_s=args.fake_delay, tts=tts)
        mode = "fake/script" if script is not None else "fake/keyboard"
    else:
        from .engine import RealEngine
        log.info("loading audio devices, TTS and Whisper '%s'…", cfg.stt.model)
        engine = RealEngine(cfg)
        mode = "real"

    service = VoiceService(engine)
    srv = build_server(service, cfg, port=args.port)
    host, port = srv.server_address[:2]
    log.info("voice node (%s) on http://%s:%s", mode, host, port)

    def _shutdown(*_):
        service.stop()
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    try:
        srv.serve_forever(poll_interval=0.2)
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
