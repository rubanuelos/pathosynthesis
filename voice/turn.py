"""voice/turn.py — end-of-turn state machine. Pure Python, no audio, unit-tested.

Fed one boolean per 30 ms frame (voiced / not voiced) and decides when the
visitor's turn is over:

    waiting  --onset-->  speaking  --end_silence_s of silence-->  "ok"
       |                    |
       |                    +--short burst (< min_voiced_s) then silence--> back to waiting
       |                    +--listen_max_s reached--> "timeout"
       +--no onset by min(no_speech_timeout_s, listen_max_s)--> "silence"

Onset needs onset_ratio of the last onset_window_ms voiced, so single clicks
don't start a turn. People pause before answering, so waiting uses its own
timeout (config listen.no_speech_timeout_s), not end_silence_s.
"""
from __future__ import annotations

from collections import deque

FRAME_S = 0.03  # 30 ms frames (webrtcvad accepts 10/20/30 ms)


class TurnDetector:
    def __init__(self, end_silence_s: float, listen_max_s: float, *,
                 no_speech_timeout_s: float = 12.0, onset_window_ms: int = 300,
                 onset_ratio: float = 0.6, min_voiced_s: float = 0.35):
        self.end_silence_frames = max(1, round(end_silence_s / FRAME_S))
        self.max_frames = max(1, round(listen_max_s / FRAME_S))
        self.no_speech_frames = max(1, round(min(no_speech_timeout_s, listen_max_s) / FRAME_S))
        win = max(1, round(onset_window_ms / 1000 / FRAME_S))
        self.window: deque[bool] = deque(maxlen=win)
        self.onset_needed = max(1, round(win * onset_ratio))
        self.min_voiced_frames = max(1, round(min_voiced_s / FRAME_S))

        self.n = 0                    # frames consumed
        self.speaking = False
        self.onset: int | None = None  # frame index where the turn's speech starts
        self.last_voiced: int | None = None
        self.voiced = 0               # voiced frames since onset
        self.silence_run = 0

    @property
    def elapsed_s(self) -> float:
        return self.n * FRAME_S

    @property
    def speech_s(self) -> float:
        """Onset to last voiced frame (contract `speech_s`)."""
        if self.onset is None or self.last_voiced is None:
            return 0.0
        return (self.last_voiced - self.onset + 1) * FRAME_S

    def _enough_speech(self) -> bool:
        return self.voiced >= self.min_voiced_frames

    def push(self, is_voiced: bool) -> str | None:
        """Consume one frame. Returns None to keep listening, else ok|silence|timeout."""
        i = self.n
        self.n += 1
        self.window.append(bool(is_voiced))

        if not self.speaking:
            if sum(self.window) >= self.onset_needed:
                self.speaking = True
                first = next(k for k, v in enumerate(self.window) if v)  # first voiced frame
                self.onset = i - len(self.window) + 1 + first
                self.voiced = sum(self.window)
                self.last_voiced = i
                self.silence_run = 0
            elif self.n >= min(self.no_speech_frames, self.max_frames):
                return "silence"
            return None

        if is_voiced:
            self.voiced += 1
            self.last_voiced = i
            self.silence_run = 0
        else:
            self.silence_run += 1

        if self.silence_run >= self.end_silence_frames:
            if self._enough_speech():
                return "ok"
            # false onset: a cough or a knock on the box. Keep waiting.
            self.speaking = False
            self.onset = self.last_voiced = None
            self.voiced = self.silence_run = 0
            self.window.clear()
            if self.n >= min(self.no_speech_frames, self.max_frames):
                return "silence"
            return None

        if self.n >= self.max_frames:
            return "timeout" if self._enough_speech() else "silence"
        return None
