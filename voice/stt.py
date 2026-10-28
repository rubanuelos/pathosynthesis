"""voice/stt.py — local Whisper (faster-whisper / CTranslate2). Audio never leaves RAM.

Language: Whisper detects it from the answer. Visitors code-switch and short
answers are easy to misdetect (es -> pt/gl), so:
  - if the detected language is allowed (stt.languages) and confident
    (>= stt.lang_confidence), keep it;
  - else prefer the question's language (`hint`) if allowed;
  - else the most probable allowed language.
Detection happens before any decoding (segments are lazy), so forcing a
language only costs a second detection pass, not a second transcription.

Hallucination guards: Silero VAD pass (vad_filter), no conditioning on
previous text, per-segment no-speech filter, and a short list of the
subtitle-credit phrases Whisper invents on noise.
"""
from __future__ import annotations

import logging
import re

import numpy as np

from .config import STTCfg

log = logging.getLogger("voice")

HALLUCINATIONS = [
    r"thanks? (you )?for watching[.!]?",
    r"please subscribe[.!]?",
    r"subt[ií]tulos? (realizados? )?por la comunidad de amara\.org",
    r"subtitulado por la comunidad de amara\.org",
    r"gracias por ver( el v[ií]deo)?[.!]?",
    r"suscr[ií]bete( al canal)?[.!]?",
]
_HALLU = re.compile("|".join(f"(?:{p})" for p in HALLUCINATIONS), re.IGNORECASE)


def clean(text: str) -> str:
    text = _HALLU.sub("", text)
    return re.sub(r"\s+", " ", text).strip(" \t\n-–—")


class Transcriber:
    def __init__(self, cfg: STTCfg):
        from faster_whisper import WhisperModel

        self.cfg = cfg
        self.allowed = [l.lower() for l in cfg.languages]
        self.model = WhisperModel(cfg.model, device=cfg.device, compute_type=cfg.compute_type,
                                  cpu_threads=cfg.cpu_threads)

    def warmup(self) -> None:
        """First call is slow (graph init); do it before the first visitor."""
        rng = np.random.default_rng(0)
        noise = (rng.standard_normal(16000) * 1e-3).astype(np.float32)
        try:
            self.transcribe(noise, hint=None)
        except Exception as exc:  # warmup must never block startup
            log.warning("stt warmup failed (%s); first answer will be slower", exc)

    def _choose(self, info, hint: str | None) -> str:
        det = info.language
        if not self.allowed:
            return det
        if det in self.allowed and info.language_probability >= self.cfg.lang_confidence:
            return det
        hint = (hint or "").split("-")[0].lower()
        if hint in self.allowed:
            return hint
        probs = dict(info.all_language_probs or [])
        return max(self.allowed, key=lambda l: probs.get(l, 0.0))

    def _run(self, audio16k: np.ndarray, language: str | None):
        return self.model.transcribe(
            audio16k,
            language=language,
            beam_size=self.cfg.beam_size,
            vad_filter=self.cfg.vad_filter,
            condition_on_previous_text=False,
            temperature=0.0,
        )

    def transcribe(self, audio16k: np.ndarray, hint: str | None) -> tuple[str, str]:
        """Returns (text, lang). Empty text means nothing usable was said."""
        segments, info = self._run(audio16k, None)
        lang = self._choose(info, hint)
        if lang != info.language:
            log.info("stt: detected %s (p=%.2f) -> using %s", info.language,
                     info.language_probability, lang)
            segments, info = self._run(audio16k, lang)
        parts = []
        for seg in segments:
            if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
                continue
            parts.append(seg.text)
        return clean(" ".join(parts)), lang
