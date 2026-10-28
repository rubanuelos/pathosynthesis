"""voice/audio.py — devices, resampling, and interruptible playback on R only.

Routing rule (contract §1.1, §2.4): the voice plays on ONE output channel of
the shared 2-ch interface, R by default, and never on the chair channel (L).
check_output_routing() enforces it at startup; play_mono() writes only that
column of the output buffer, every other column is zeros. On macOS CoreAudio
several clients mix additively on one device, so our zeros on L do not touch
SuperCollider's chair layer.

Open the device at SuperCollider's sample rate (config output.samplerate) so
the hardware rate is never renegotiated under scsynth.
"""
from __future__ import annotations

import logging
import threading
import time
import wave
from math import gcd
from pathlib import Path

import numpy as np

from .config import CHAIR_CHANNEL, InputCfg, OutputCfg

log = logging.getLogger("voice")


def _sd():
    import sounddevice as sd  # lazy: keeps imports cheap for tests
    return sd


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
def resolve_device(spec: str | int | None, kind: str) -> int | None:
    """Device index from a config value: int index, name substring, or None (default)."""
    sd = _sd()
    if spec is None:
        return None
    if isinstance(spec, int) or (isinstance(spec, str) and spec.isdigit()):
        return int(spec)
    key = "max_output_channels" if kind == "output" else "max_input_channels"
    for i, d in enumerate(sd.query_devices()):
        if spec.lower() in d["name"].lower() and d[key] > 0:
            return i
    raise RuntimeError(f"no {kind} device matching {spec!r}; see `python -m voice.check devices`")


def device_info(spec, kind: str) -> dict:
    sd = _sd()
    idx = resolve_device(spec, kind)
    return sd.query_devices(idx, kind) if idx is not None else sd.query_devices(kind=kind)


def device_rate(spec, kind: str, configured: int | None) -> int:
    return int(configured or device_info(spec, kind)["default_samplerate"])


def check_output_routing(cfg: OutputCfg) -> None:
    """Safety, in code: the voice can never be routed to the chair channel."""
    if cfg.channel == CHAIR_CHANNEL:
        raise RuntimeError(f"output.channel={cfg.channel} is the chair shaker (L). "
                           "The voice never plays there (contract §1.1).")
    if cfg.channel < 1:
        raise RuntimeError("output.channel is 1-based")
    info = device_info(cfg.device, "output")
    if info["max_output_channels"] < cfg.channel:
        raise RuntimeError(f"output device {info['name']!r} has {info['max_output_channels']} "
                           f"channels; output.channel={cfg.channel} does not exist")
    log.info("voice out: %s, channel %d only, %s Hz", info["name"], cfg.channel,
             cfg.samplerate or int(info["default_samplerate"]))


def check_input(cfg: InputCfg) -> None:
    info = device_info(cfg.device, "input")
    if info["max_input_channels"] < cfg.channel:
        raise RuntimeError(f"input device {info['name']!r} has {info['max_input_channels']} "
                           f"channels; input.channel={cfg.channel} does not exist")
    log.info("voice in: %s, channel %d, %s Hz", info["name"], cfg.channel,
             cfg.samplerate or int(info["default_samplerate"]))


# --------------------------------------------------------------------------- #
# Signal helpers
# --------------------------------------------------------------------------- #
def db_to_amp(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if int(sr_in) == int(sr_out):
        return x.astype(np.float32, copy=False)
    from scipy.signal import resample_poly
    g = gcd(int(sr_in), int(sr_out))
    return resample_poly(x, int(sr_out) // g, int(sr_in) // g).astype(np.float32)


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """16-bit PCM WAV -> mono float32 in [-1, 1]."""
    with wave.open(str(path), "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise RuntimeError(f"{path}: expected 16-bit PCM, got {8 * width}-bit")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def load_cue(path: str | None) -> tuple[np.ndarray, int] | None:
    if not path:
        return None
    return read_wav(path)


def prepare(buf: np.ndarray, sr: int, cfg: OutputCfg, normalize: bool = True) -> tuple[np.ndarray, int]:
    """Resample to the device rate, normalise, apply room gain, hard-cap the peak."""
    out_sr = device_rate(cfg.device, "output", cfg.samplerate)
    x = resample(np.asarray(buf, dtype=np.float32), sr, out_sr)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if normalize and peak > 1e-6:
        x = x * (db_to_amp(cfg.peak_dbfs) / peak)
    x = x * db_to_amp(cfg.gain_db)
    ceiling = db_to_amp(min(cfg.max_peak_dbfs, 0.0))
    np.clip(x, -ceiling, ceiling, out=x)  # safety ceiling, whatever the config says
    return x.astype(np.float32, copy=False), out_sr


# --------------------------------------------------------------------------- #
# Playback
# --------------------------------------------------------------------------- #
def play_mono(x: np.ndarray, sr: int, cfg: OutputCfg, cancel: threading.Event) -> bool:
    """Play an already-prepared mono buffer on cfg.channel only.

    Blocks until done. If `cancel` is set, fades out over cfg.fade_ms and
    returns False. Returns True when the buffer played to the end.
    """
    if cfg.channel == CHAIR_CHANNEL:  # belt and braces; checked at startup too
        raise RuntimeError("refusing to play the voice on the chair channel")
    sd = _sd()
    dev = resolve_device(cfg.device, "output")
    col = cfg.channel - 1
    fade_len = max(1, int(sr * cfg.fade_ms / 1000.0))
    state = {"pos": 0, "fade": -1}  # fade < 0: not fading; else samples already faded
    done = threading.Event()

    def callback(outdata, frames, _time, status):
        if status:
            log.debug("output status: %s", status)
        outdata.fill(0.0)
        pos = state["pos"]
        if cancel.is_set() and state["fade"] < 0:
            state["fade"] = 0
        if state["fade"] >= 0:
            f = state["fade"]
            m = min(frames, fade_len - f, len(x) - pos)
            if m > 0:
                ramp = 1.0 - (np.arange(f, f + m, dtype=np.float32) / fade_len)
                outdata[:m, col] = x[pos:pos + m] * ramp
                state["pos"] += m
                state["fade"] += m
            if m <= 0 or state["fade"] >= fade_len:
                raise sd.CallbackStop
            return
        chunk = x[pos:pos + frames]
        outdata[:len(chunk), col] = chunk
        state["pos"] += len(chunk)
        if len(chunk) < frames:
            raise sd.CallbackStop

    stream = sd.OutputStream(device=dev, samplerate=sr, channels=cfg.channel, dtype="float32",
                             callback=callback, finished_callback=done.set)
    # Watchdog: never block longer than the buffer + 2 s (device hiccup, unplug).
    limit = time.monotonic() + len(x) / sr + 2.0
    with stream:
        while not done.wait(0.05):
            if time.monotonic() > limit:
                stream.abort()
                raise RuntimeError("output stream stalled")
    return not cancel.is_set()
