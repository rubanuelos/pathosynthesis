"""voice/kokoro_worker.py — persistent Kokoro-82M renderer for the voice node.

Runs inside voice/.venvs/mlx (Python 3.12 + mlx-audio + misaki; made by
`bash voice/bakeoff_setup.sh mlx`), NOT the project venv, so it must not import
the `voice` package. tts.KokoroTTS starts it once and keeps it alive, so the
model loads at startup and each question only pays the render (~0.1-0.3 s).

Protocol: JSON lines on stdin/stdout (logs go to stderr).
    stdin  line 1:  {"repo": "prince-canuma/Kokoro-82M", "warm": [{"voice": "af_heart", "lang_code": "a"}, …]}
    stdout:         {"ready": true, "load_s": 7.1}
    stdin:          {"id": 1, "text": "…?", "voice": "af_heart", "lang_code": "a",
                     "speed": 0.8, "pause_s": 0.5, "out": "/tmp/…/q.wav"}
    stdout:         {"id": 1, "ok": true, "render_s": 0.21, "audio_s": 4.3}
                    {"id": 1, "ok": false, "error": "…"}
Exits when stdin closes (the voice node stopped).

Calm delivery, done here because only Kokoro sees the text:
  - `speed` < 1 slows the whole delivery;
  - a question made of several sentences ("Years of it. What do the hands do…?")
    is rendered sentence by sentence and joined with `pause_s` of silence, so the
    fragment gets room before the question. Commas are left to the model: splitting
    there would give each half a final, falling intonation.
"""
import json
import re
import sys
import time
import traceback
import wave

import numpy as np

SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=\S)")


def write_wav(path, x, sr):
    pcm = (np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())


def render(model, text, voice, lang_code, speed):
    results = list(model.generate(text=text, voice=voice, speed=speed, lang_code=lang_code,
                                  split_pattern=r"\n+"))
    audio = np.concatenate([np.array(r.audio, dtype=np.float32).reshape(-1) for r in results])
    return audio, int(results[0].sample_rate)


def main():
    from mlx_audio.tts.utils import load_model

    setup = json.loads(sys.stdin.readline())
    t0 = time.monotonic()
    model = load_model(setup["repo"])
    for w in setup.get("warm", []):  # load G2P + voice packs before the first visitor
        render(model, "Hello?" if w["lang_code"] in "ab" else "¿Hola?", w["voice"], w["lang_code"], 1.0)
    print(json.dumps({"ready": True, "load_s": round(time.monotonic() - t0, 2)}), flush=True)

    for line in sys.stdin:
        if not line.strip():
            continue
        req = {}
        try:
            req = json.loads(line)
            t1 = time.monotonic()
            parts = [p for p in SENTENCE_END.split(" ".join(req["text"].split())) if p]
            chunks, sr = [], 24000
            for i, part in enumerate(parts):
                audio, sr = render(model, part, req["voice"], req["lang_code"], float(req["speed"]))
                if i:
                    chunks.append(np.zeros(int(sr * float(req.get("pause_s", 0.0))), np.float32))
                chunks.append(audio)
            x = np.concatenate(chunks)
            write_wav(req["out"], x, sr)
            print(json.dumps({"id": req.get("id"), "ok": True,
                              "render_s": round(time.monotonic() - t1, 3),
                              "audio_s": round(len(x) / sr, 2)}), flush=True)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"id": req.get("id"), "ok": False,
                              "error": f"{type(exc).__name__}: {exc}"[:400]}), flush=True)


if __name__ == "__main__":
    main()
