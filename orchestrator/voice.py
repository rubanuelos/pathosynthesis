"""HTTP client for the voice node (contract v0.3 §2.4), plus a fake voice node for tests and --dialogue.

VoiceClient.ask() never raises on a bad or missing voice node: it returns an exchange-like dict with
status "timeout" and logs the error, so the session keeps moving (§7.4: the piece never stalls).
`ok` in the result tells the session whether the node answered at all.

FakeVoice: a tiny HTTP server with the same three endpoints that returns canned answers in order.
    python -m orchestrator.voice contract/examples/dialogue_habit_build.json      # serve on :8010
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("pathos.voice")

VOICE_URL = "http://127.0.0.1:8010"
LISTEN_MAX_S = 45.0
END_SILENCE_S = 2.5
SPEAK_ALLOWANCE_S = 30.0      # HTTP timeout = listen_max_s + this (TTS of a ≤ 25-word question)
STATUSES = {"ok", "silence", "timeout"}


class VoiceClient:
    def __init__(self, base_url: str = VOICE_URL, listen_max_s: float = LISTEN_MAX_S,
                 end_silence_s: float = END_SILENCE_S):
        self.base = base_url.rstrip("/")
        self.listen_max_s = listen_max_s
        self.end_silence_s = end_silence_s

    def _post(self, path: str, body: dict, timeout: float) -> dict:
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    def health(self, timeout: float = 1.0) -> bool:
        try:
            with urllib.request.urlopen(self.base + "/health", timeout=timeout) as r:
                return bool(json.loads(r.read()).get("ok"))
        except (OSError, ValueError):
            return False

    def ask(self, text: str, lang: str = "en") -> dict:
        """-> {"answer", "status", "speech_s"?, "lang"?, "ok": bool}"""
        body = {"text": text, "lang": lang, "listen_max_s": self.listen_max_s, "end_silence_s": self.end_silence_s}
        try:
            r = self._post("/ask", body, timeout=self.listen_max_s + SPEAK_ALLOWANCE_S)
        except (OSError, ValueError) as e:     # URLError, timeouts, bad JSON
            log.error("voice /ask failed: %s", e)
            return {"answer": "", "status": "timeout", "ok": False}
        status = r.get("status")
        answer = r.get("answer", "")
        if status not in STATUSES or not isinstance(answer, str):
            log.error("voice /ask returned a malformed response: %r", r)
            return {"answer": "", "status": "timeout", "ok": False}
        out = {"answer": answer[:2000], "status": status, "ok": True}
        if isinstance(r.get("speech_s"), (int, float)) and r["speech_s"] >= 0:
            out["speech_s"] = float(r["speech_s"])
        if isinstance(r.get("lang"), str) and r["lang"]:
            out["lang"] = r["lang"][:16]
        return out

    def stop(self) -> None:
        try:
            self._post("/stop", {}, timeout=1.0)
        except (OSError, ValueError) as e:
            log.warning("voice /stop failed: %s", e)


# =============================================================================
# Fake voice node
# =============================================================================

class FakeVoice:
    """Serves canned answers in order. After they run out it answers `silence`.

    `answers`: list of {"answer", "status", "speech_s"?}. `delay_s` simulates speaking + listening.
    /stop interrupts a pending /ask (it then returns status "timeout").
    """

    def __init__(self, answers: list[dict], lang: str = "en", host: str = "127.0.0.1", port: int = 8010,
                 delay_s: float = 0.2):
        self.answers = list(answers)
        self.lang = lang
        self.delay_s = delay_s
        self.asked: list[str] = []
        self.stops = 0
        self._i = 0
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._server = ThreadingHTTPServer((host, port), self._handler())
        self._server.daemon_threads = True

    @classmethod
    def from_dialogue(cls, dialogue: dict, **kw) -> "FakeVoice":
        ans = [{k: e[k] for k in ("answer", "status", "speech_s") if k in e} for e in dialogue["exchanges"]]
        return cls(ans, lang=dialogue.get("lang", "en"), **kw)

    @property
    def url(self) -> str:
        h, p = self._server.server_address[:2]
        return f"http://{h}:{p}"

    def start(self) -> "FakeVoice":
        threading.Thread(target=self._server.serve_forever, name="fake-voice", daemon=True).start()
        log.info("fake voice node on %s (%d canned answers)", self.url, len(self.answers))
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _next(self, text: str) -> dict:
        with self._lock:
            self.asked.append(text)
            self._stop_evt.clear()
            if self._i < len(self.answers):
                a = dict(self.answers[self._i])
            else:
                a = {"answer": "", "status": "silence", "speech_s": 0.0}
            self._i += 1
        if self._stop_evt.wait(self.delay_s):
            return {"answer": "", "status": "timeout", "lang": self.lang}
        a.setdefault("lang", self.lang)
        return a

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):   # quiet
                pass

            def _reply(self, obj: dict, code: int = 200) -> None:
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._reply({"ok": True} if self.path == "/health" else {"error": "not found"},
                            200 if self.path == "/health" else 404)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._reply({"error": "bad json"}, 400)
                if self.path == "/ask":
                    log.info("fake voice asks: %s", body.get("text"))
                    return self._reply(fake._next(str(body.get("text", ""))))
                if self.path == "/stop":
                    fake.stops += 1
                    fake._stop_evt.set()
                    return self._reply({"ok": True})
                self._reply({"error": "not found"}, 404)

        return H


if __name__ == "__main__":   # standalone fake voice node
    import argparse
    import sys

    p = argparse.ArgumentParser(description="fake voice node: canned answers from a dialogue file")
    p.add_argument("dialogue")
    p.add_argument("--port", type=int, default=8010)
    p.add_argument("--delay", type=float, default=1.0)
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    fv = FakeVoice.from_dialogue(json.loads(open(a.dialogue).read()), port=a.port, delay_s=a.delay).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        fv.close()
        sys.exit(0)
