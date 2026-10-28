"""voice/tts.py — text -> mono buffer -> R channel.

Engines render to a temporary WAV (TTS output only; no visitor audio ever
touches disk), then audio.play_mono() plays it on the configured channel with
a fade on /stop. The voice itself (engine, voice name per language, rate) is
config: it is part of the piece.

    say    macOS built-in, offline. `say -v '?'` lists voices.
    piper  offline neural TTS (github.com/rhasspy/piper); one .onnx voice per language.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

from . import audio
from .config import OutputCfg, TTSCfg

log = logging.getLogger("voice")
RENDER_TIMEOUT_S = 20


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
        buf = audio.prepare(raw, sr, self.out)
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
        cmd = [self.cfg.piper_bin, "--model", model, "--output_file", str(wav_path),
               "--length_scale", str(self.cfg.piper_length_scale)]
        proc = subprocess.run(cmd, input=text, capture_output=True, text=True,
                              timeout=RENDER_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError(f"piper failed: {proc.stderr.strip()[-400:]}")


ENGINES = {"say": SayTTS, "piper": PiperTTS}


def make(cfg: TTSCfg, out: OutputCfg) -> TTS:
    try:
        return ENGINES[cfg.engine](cfg, out)
    except KeyError:
        raise RuntimeError(f"unknown tts.engine {cfg.engine!r}; choose {sorted(ENGINES)}") from None
