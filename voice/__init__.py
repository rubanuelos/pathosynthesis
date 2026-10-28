"""Pathosynthesis node 06 — Voice (mic, STT, TTS).

Local HTTP service on 127.0.0.1:8010 (contract §2.4):
    POST /ask   speak a question on R only, listen, transcribe
    POST /stop  cut speech and listening now
    GET  /health

Run:  python -m voice.serve            (real audio)
      python -m voice.serve --fake     (keyboard answers, no audio deps)
"""
