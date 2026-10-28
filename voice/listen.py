"""voice/listen.py — mic capture, frame VAD, end-of-turn. Audio stays in RAM.

Capture runs at the device rate (no reliance on driver resampling). Each 30 ms
block is resampled to 16 kHz for the frame classifier; the whole turn is
resampled once at the end for Whisper (avoids per-block edge artefacts).

Frame classifier = energy gate AND webrtcvad. The gate (listen.speech_gate_dbfs)
rejects distant gallery chatter because the visitor's mouth is close to the
mic; webrtcvad rejects non-speech noise above the gate. If webrtcvad is not
installed the gate alone decides (logged once).
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from . import audio
from .config import Config, ListenCfg
from .turn import FRAME_S, TurnDetector

log = logging.getLogger("voice")
STT_SR = 16000
FRAME_16K = int(STT_SR * FRAME_S)  # 480


@dataclass
class Turn:
    status: str                 # ok | silence | timeout | stopped
    audio: np.ndarray | None    # 16 kHz mono float32, trimmed around the speech
    speech_s: float


class FrameClassifier:
    _warned = False

    def __init__(self, cfg: ListenCfg):
        self.gate = cfg.speech_gate_dbfs
        try:
            import webrtcvad
            self.vad = webrtcvad.Vad(int(cfg.vad_aggressiveness))
        except ImportError:
            self.vad = None
            if not FrameClassifier._warned:
                log.warning("webrtcvad not installed: energy-gate VAD only")
                FrameClassifier._warned = True

    @staticmethod
    def dbfs(frame: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0
        return 20.0 * np.log10(rms + 1e-12)

    def __call__(self, frame16k: np.ndarray) -> bool:
        if self.dbfs(frame16k) < self.gate:
            return False
        if self.vad is None:
            return True
        pcm = (np.clip(frame16k, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        return self.vad.is_speech(pcm, STT_SR)


def to_frame16k(block: np.ndarray, sr: int) -> np.ndarray:
    f = audio.resample(block, sr, STT_SR)
    if len(f) < FRAME_16K:
        f = np.pad(f, (0, FRAME_16K - len(f)))
    return f[:FRAME_16K]


def open_input(cfg: Config):
    """Returns (stream, queue, sr, block). Each queue item is one 30 ms mono block."""
    sd = audio._sd()
    icfg = cfg.input
    dev = audio.resolve_device(icfg.device, "input")
    sr = audio.device_rate(icfg.device, "input", icfg.samplerate)
    block = int(round(sr * FRAME_S))
    q: queue.Queue[np.ndarray] = queue.Queue()
    col = icfg.channel - 1
    gain = audio.db_to_amp(icfg.gain_db)

    def callback(indata, frames, _time, status):
        if status:
            log.debug("input status: %s", status)
        q.put(indata[:, col].copy() * gain)

    stream = sd.InputStream(device=dev, samplerate=sr, channels=icfg.channel, blocksize=block,
                            dtype="float32", callback=callback)
    return stream, q, sr, block


def capture_turn(cfg: Config, end_silence_s: float, listen_max_s: float,
                 cancel: threading.Event) -> Turn:
    L = cfg.listen
    det = TurnDetector(end_silence_s, listen_max_s, no_speech_timeout_s=L.no_speech_timeout_s,
                       onset_window_ms=L.onset_window_ms, onset_ratio=L.onset_ratio,
                       min_voiced_s=L.min_voiced_s)
    clf = FrameClassifier(L)
    blocks: list[np.ndarray] = []
    stream, q, sr, _block = open_input(cfg)
    status: str | None = None
    with stream:
        last_block = time.monotonic()
        while status is None:
            if cancel.is_set():
                return Turn("stopped", None, 0.0)
            try:
                blk = q.get(timeout=0.1)
            except queue.Empty:
                if time.monotonic() - last_block > L.mic_stall_s:
                    raise RuntimeError("microphone stopped delivering audio")
                continue
            last_block = time.monotonic()
            blocks.append(blk)
            status = det.push(clf(to_frame16k(blk, sr)))

    if status == "silence" or det.onset is None:
        blocks.clear()
        return Turn("silence", None, 0.0)

    start = max(0, det.onset - int(L.preroll_s / FRAME_S))
    end = min(len(blocks), (det.last_voiced or det.onset) + 1 + int(L.tail_s / FRAME_S))
    speech = audio.resample(np.concatenate(blocks[start:end]), sr, STT_SR)
    blocks.clear()
    return Turn(status, speech, det.speech_s)
