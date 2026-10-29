"""voice/tts.py — text -> mono buffer -> R channel.

Engines render to a temporary WAV (TTS output only; no visitor audio ever
touches disk), then audio.play_mono() plays it on the configured channel with
a fade on /stop. The voice itself (engine, voice name per language, rate) is
config: it is part of the piece.

    kokoro Kokoro-82M via mlx-audio (Apple Silicon), the team's choice (voice bake-off,
           2026-10-29). Runs as a persistent worker in voice/.venvs/mlx (see
           voice/kokoro_worker.py); if it can't start or a render fails, the
           tts.fallback engine speaks instead, so the piece never goes silent.
    say    macOS built-in, offline. `say -v '?'` lists voices.
    piper  offline neural TTS (github.com/rhasspy/piper); one .onnx voice per language.

tts.warmth_db applies to every engine: a gentle high-shelf cut (above ~4.5 kHz)
that takes the edge off sibilants and brightness on the small speaker. 0 = off.
"""
from __future__ import annotations

import atexit
import json
import logging
import queue
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np

from . import audio
from .config import OutputCfg, TTSCfg

log = logging.getLogger("voice")
RENDER_TIMEOUT_S = 20
REPO_DIR = Path(__file__).resolve().parent.parent


def soften(x: np.ndarray, sr: int, gain_db: float, freq_hz: float = 4500.0) -> np.ndarray:
    """RBJ high-shelf (S = 1). gain_db < 0 cuts above freq_hz; 0 returns x unchanged."""
    if not gain_db or not x.size:
        return x
    from scipy.signal import lfilter
    A = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * min(freq_hz, 0.45 * sr) / sr
    cw, alpha = np.cos(w0), np.sin(w0) / 2 * np.sqrt(2)
    sa = 2 * np.sqrt(A) * alpha
    b = [A * ((A + 1) + (A - 1) * cw + sa), -2 * A * ((A - 1) + (A + 1) * cw),
         A * ((A + 1) + (A - 1) * cw - sa)]
    a = [(A + 1) - (A - 1) * cw + sa, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sa]
    return lfilter(np.array(b) / a[0], np.array(a) / a[0], x).astype(np.float32)


class TTS:
    def __init__(self, cfg: TTSCfg, out: OutputCfg):
        self.cfg = cfg
        self.out = out
        self._cache: OrderedDict[tuple, tuple[np.ndarray, int]] = OrderedDict()

    # -- engine-specific ----------------------------------------------------
    def _render(self, text: str, lang: str, wav_path: Path) -> None:
        raise NotImplementedError

    def _voice_key(self, lang: str) -> str:
        raise NotImplementedError

    # -- shared ---------------------------------------------------------------
    def _lang(self, lang: str) -> str:
        base = (lang or self.cfg.default_lang).split("-")[0].lower()
        return base

    def synth(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        """Rendered, resampled, gain-staged buffer at the output rate (cached)."""
        key = (self.cfg.engine, self._voice_key(self._lang(lang)), text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        with tempfile.TemporaryDirectory(prefix="pathos-tts-") as d:
            wav_path = Path(d) / "q.wav"
            self._render(text, self._lang(lang), wav_path)
            raw, sr = audio.read_wav(wav_path)
        buf = audio.prepare(soften(raw, sr, self.cfg.warmth_db), sr, self.out)
        self._cache[key] = buf
        while len(self._cache) > max(self.cfg.cache_size, 0):
            self._cache.popitem(last=False)
        return buf

    def speak(self, text: str, lang: str, cancel: threading.Event) -> bool:
        x, sr = self.synth(text, lang)
        if cancel.is_set():
            return False
        return audio.play_mono(x, sr, self.out, cancel)

    def play_buffer(self, raw: np.ndarray, sr: int, cancel: threading.Event) -> bool:
        """Play a non-speech sound (e.g. the listen cue) through the same safe path."""
        x, out_sr = audio.prepare(raw, sr, self.out, normalize=False)
        return audio.play_mono(x, out_sr, self.out, cancel)


class SayTTS(TTS):
    def _voice_key(self, lang: str) -> str:
        return self.cfg.voices.get(lang) or self.cfg.voices.get(self.cfg.default_lang) or ""

    def _render(self, text: str, lang: str, wav_path: Path) -> None:
        txt = wav_path.with_suffix(".txt")
        txt.write_text(text, encoding="utf-8")  # -f: safe for any text, incl. leading '-'
        cmd = ["say", "-o", str(wav_path), "--file-format=WAVE", "--data-format=LEI16@22050",
               "-f", str(txt)]
        voice = self._voice_key(lang)
        if voice:
            cmd += ["-v", voice]
        if self.cfg.rate_wpm:
            cmd += ["-r", str(int(self.cfg.rate_wpm))]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT_S)
        if proc.returncode != 0 and voice:
            # Missing voice on this machine: say it, then fall back to the system voice.
            log.warning("say voice %r failed (%s); using system default", voice, proc.stderr.strip())
            cmd = [c for c in cmd if c not in ("-v", voice)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"say failed: {proc.stderr.strip()}")


class PiperTTS(TTS):
    def _voice_key(self, lang: str) -> str:
        m = self.cfg.piper_models
        return m.get(lang) or m.get(self.cfg.default_lang) or ""

    def _render(self, text: str, lang: str, wav_path: Path) -> None:
        model = self._voice_key(lang)
        if not model:
            raise RuntimeError(f"no piper model for '{lang}' or default; set tts.piper_models")
        # piper-tts (piper1-gpl) CLI: `piper -m MODEL -f OUT.wav --length-scale X -i TEXT.txt`.
        # Not `-- text`: piper reads trailing args with parse_known_args, which
        # keeps the `--` (Python 3.11-3.13), so it would be spoken. Bare trailing
        # args break on text starting with '-'. An input file is safe for any
        # text; one line = one utterance (piper synthesizes per line).
        txt = wav_path.with_suffix(".txt")
        txt.write_text(" ".join(text.split()) + "\n", encoding="utf-8")
        cmd = [self.cfg.piper_bin, "-m", model, "-f", str(wav_path),
               "--length-scale", str(self.cfg.piper_length_scale), "-i", str(txt)]
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=RENDER_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"piper failed: {proc.stderr.strip()[-400:]}")


KOKORO_LANG_CODES = {"en": "a", "es": "e"}  # Kokoro/misaki: a = American English, e = Spanish


class KokoroTTS(TTS):
    """Kokoro-82M in a persistent worker process (own venv, see kokoro_worker.py).

    Startup loads the model (~7 s; the first run ever downloads it). A render
    that fails or takes longer than RENDER_TIMEOUT_S kills the worker, the
    question is spoken by `fallback`, and the worker restarts on the next one.
    """

    def __init__(self, cfg: TTSCfg, out: OutputCfg, fallback: TTS | None = None):
        super().__init__(cfg, out)
        self.fallback = fallback
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._next_id = 0
        self._start()
        atexit.register(self.close)

    # -- worker ------------------------------------------------------------------
    def _python(self) -> Path:
        p = Path(self.cfg.kokoro_python)
        return p if p.is_absolute() else REPO_DIR / p

    def _start(self) -> None:
        py = self._python()
        if not py.exists():
            raise RuntimeError(f"Kokoro venv not found at {py}: run `bash voice/bakeoff_setup.sh mlx`")
        self._lines = queue.Queue()
        self._proc = subprocess.Popen(
            [str(py), str(Path(__file__).with_name("kokoro_worker.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1, cwd=str(REPO_DIR))
        proc, lines = self._proc, self._lines

        def read_stdout():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)  # worker gone

        def read_stderr():
            for line in proc.stderr:
                log.debug("kokoro: %s", line.rstrip())

        threading.Thread(target=read_stdout, daemon=True, name="kokoro-out").start()
        threading.Thread(target=read_stderr, daemon=True, name="kokoro-err").start()
        warm = [{"voice": self._voice(l), "lang_code": c} for l, c in KOKORO_LANG_CODES.items()
                if l in self.cfg.kokoro_voices]
        self._send({"repo": self.cfg.kokoro_repo, "warm": warm})
        msg = self._recv(self.cfg.kokoro_start_timeout_s)
        if not msg.get("ready"):
            self.close()
            raise RuntimeError(f"Kokoro worker failed to start: {msg}")
        log.info("kokoro ready in %.1fs (%s)", msg.get("load_s", 0),
                 ", ".join(f"{l}: {self._voice(l)} @ {self._speed(l)}" for l in self.cfg.kokoro_voices))

    def _send(self, obj: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _recv(self, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self._lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError(f"no answer from the Kokoro worker within {timeout:.0f}s") from None
            if line is None:
                raise RuntimeError("Kokoro worker exited (see voice log with -v)")
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                log.debug("kokoro stdout: %s", line.rstrip())  # stray library print

    def close(self) -> None:
        p, self._proc = self._proc, None
        if p and p.poll() is None:
            try:
                p.stdin.close()  # the worker exits on EOF
                p.wait(timeout=3)
            except Exception:
                p.kill()

    # -- TTS interface -----------------------------------------------------------
    def _voice(self, lang: str) -> str:
        v = self.cfg.kokoro_voices
        return v.get(lang) or v.get(self.cfg.default_lang) or "af_heart"

    def _speed(self, lang: str) -> float:
        s = self.cfg.kokoro_speed
        return float(s.get(lang) or s.get(self.cfg.default_lang) or 1.0)

    def _voice_key(self, lang: str) -> str:
        return f"{self._voice(lang)}@{self._speed(lang)}/{self.cfg.kokoro_pause_s}"

    def _render(self, text: str, lang: str, wav_path: Path) -> None:
        code = KOKORO_LANG_CODES.get(lang)
        if code is None:
            raise RuntimeError(f"Kokoro is not set up for '{lang}' (have {sorted(KOKORO_LANG_CODES)})")
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                log.warning("restarting the Kokoro worker")
                self._start()
            self._next_id += 1
            rid = self._next_id
            self._send({"id": rid, "text": " ".join(text.split()), "voice": self._voice(lang),
                        "lang_code": code, "speed": self._speed(lang),
                        "pause_s": self.cfg.kokoro_pause_s, "out": str(wav_path)})
            try:
                while True:
                    msg = self._recv(RENDER_TIMEOUT_S)
                    if msg.get("id") == rid:
                        break
            except Exception:
                self.close()  # hung or dead: restart on the next question
                raise
        if not msg.get("ok"):
            raise RuntimeError(f"kokoro: {msg.get('error')}")
        log.debug("kokoro render %.2fs for %.1fs of audio", msg.get("render_s", 0), msg.get("audio_s", 0))

    def synth(self, text: str, lang: str) -> tuple[np.ndarray, int]:
        try:
            return super().synth(text, lang)
        except Exception as exc:
            if self.fallback is None:
                raise
            log.error("kokoro failed (%s); this question uses tts.fallback=%s",
                      exc, self.cfg.fallback)
            return self.fallback.synth(text, lang)


ENGINES = {"kokoro": KokoroTTS, "say": SayTTS, "piper": PiperTTS}


def _make_one(engine: str, cfg: TTSCfg, out: OutputCfg) -> TTS:
    try:
        return ENGINES[engine](cfg, out)
    except KeyError:
        raise RuntimeError(f"unknown tts engine {engine!r}; choose {sorted(ENGINES)}") from None


def make(cfg: TTSCfg, out: OutputCfg) -> TTS:
    if cfg.engine != "kokoro":
        return _make_one(cfg.engine, cfg, out)
    fallback = None
    if cfg.fallback and cfg.fallback != "kokoro":
        try:
            fallback = _make_one(cfg.fallback, cfg, out)
        except Exception as exc:
            log.warning("tts.fallback %r unavailable: %s", cfg.fallback, exc)
    try:
        return KokoroTTS(cfg, out, fallback=fallback)
    except Exception as exc:
        if fallback is None:
            raise
        log.error("Kokoro unavailable (%s); speaking with tts.fallback=%s", exc, cfg.fallback)
        return fallback
