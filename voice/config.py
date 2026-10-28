"""voice/config.py — built-in defaults, overlaid by voice/config.toml.

Every section is a dataclass; the TOML file only needs the keys you change.
TOML has no null: use "" (empty string) for "None / system default".

Stdlib only, so --fake mode runs without numpy/sounddevice/whisper.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

# Contract §1.1: out 0 / L / channel 1 is the chair bass shaker.
# The voice is NEVER routed there. Checked in code at startup (audio.py).
CHAIR_CHANNEL = 1

CONTRACT_VERSION = "0.3"
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.toml")


@dataclass
class ServerCfg:
    host: str = "127.0.0.1"
    port: int = 8010


@dataclass
class OutputCfg:
    # Device: substring of the device name, an integer index, or None = system default.
    device: str | int | None = None
    # 1-based channel. 2 = R = 8" speaker under the water container (contract §1.1).
    channel: int = 2
    # Open the device at SuperCollider's rate (s.options.sampleRate) so nothing
    # renegotiates the hardware rate under scsynth. None = device's reported default.
    samplerate: int | None = 48000
    peak_dbfs: float = -6.0       # TTS is peak-normalised to this before gain_db
    gain_db: float = 0.0          # room calibration, set at install
    max_peak_dbfs: float = -1.0   # hard ceiling after gain (safety, never exceeded)
    fade_ms: float = 15.0         # fade-out on /stop, avoids a click on R
    listen_cue: str | None = None  # optional WAV played after each question (artistic hook)


@dataclass
class InputCfg:
    device: str | int | None = None
    channel: int = 1              # 1-based input channel of the mic near the object
    samplerate: int | None = 48000
    gain_db: float = 0.0          # digital gain before VAD/STT


@dataclass
class TTSCfg:
    engine: str = "say"           # "say" (macOS, offline) | "piper" (offline neural)
    default_lang: str = "en"
    # Voice per language. The voice is part of the piece: the team chooses.
    voices: dict[str, str] = field(default_factory=lambda: {"en": "Samantha", "es": "Paulina"})
    rate_wpm: int | None = 160    # `say -r`; None = voice default
    piper_bin: str = "piper"
    piper_models: dict[str, str] = field(default_factory=dict)  # lang -> path/to/voice.onnx
    piper_length_scale: float = 1.0  # >1 slower
    cache_size: int = 32          # rendered questions kept in RAM (opener, fallback probes)


@dataclass
class ListenCfg:
    delay_s: float = 0.25         # gap after TTS ends before the mic opens (speaker/room tail)
    no_speech_timeout_s: float = 12.0  # give up waiting for a first word (status: silence)
    vad_aggressiveness: int = 2   # webrtcvad 0..3
    speech_gate_dbfs: float = -50.0    # frames below this are never speech; calibrate with `voice.check meter`
    onset_window_ms: int = 300    # onset = onset_ratio of this window voiced
    onset_ratio: float = 0.6
    min_voiced_s: float = 0.35    # shorter bursts (cough, knock on the box) are discarded
    preroll_s: float = 0.4        # audio kept before onset for STT
    tail_s: float = 0.3           # audio kept after the last voiced frame
    # Clamps on the request values (safety; the piece never stalls on the voice).
    end_silence_min_s: float = 0.6
    end_silence_max_s: float = 8.0
    listen_max_cap_s: float = 120.0
    mic_stall_s: float = 2.0      # no audio blocks for this long -> error


@dataclass
class STTCfg:
    model: str = "small"          # faster-whisper size or local path ("medium", "large-v3-turbo", ...)
    device: str = "cpu"           # Apple Silicon: cpu (CTranslate2 has no Metal backend)
    compute_type: str = "int8"
    cpu_threads: int = 0          # 0 = library default
    beam_size: int = 5
    languages: list[str] = field(default_factory=lambda: ["en", "es"])  # [] = any language
    lang_confidence: float = 0.6  # below this, prefer the question's language if allowed
    vad_filter: bool = True       # faster-whisper's Silero pass: cuts hallucinations on noise
    log_transcripts: bool = False  # the orchestrator logs transcripts; keep this node quiet


@dataclass
class Config:
    server: ServerCfg = field(default_factory=ServerCfg)
    output: OutputCfg = field(default_factory=OutputCfg)
    input: InputCfg = field(default_factory=InputCfg)
    tts: TTSCfg = field(default_factory=TTSCfg)
    listen: ListenCfg = field(default_factory=ListenCfg)
    stt: STTCfg = field(default_factory=STTCfg)


def _apply(section: Any, values: dict[str, Any], name: str) -> None:
    known = {f.name for f in fields(section)}
    for key, val in values.items():
        if key not in known:
            raise ValueError(f"config [{name}] has unknown key '{key}'")
        if val == "":
            val = None
        setattr(section, key, val)


def load(path: str | Path | None = None) -> Config:
    cfg = Config()
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.exists():
        if path:  # explicitly requested and missing
            raise FileNotFoundError(p)
        return cfg
    with p.open("rb") as fh:
        data = tomllib.load(fh)
    for name, values in data.items():
        if not hasattr(cfg, name):
            raise ValueError(f"config has unknown section [{name}]")
        _apply(getattr(cfg, name), values, name)
    return cfg
