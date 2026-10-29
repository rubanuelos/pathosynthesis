"""Node 01 — Interpretation: voice questionnaire turns and score composition (contract v0.3 §2.5).

    from interpretation import next_turn, compose, InterpretationError
"""
__all__ = ["next_turn", "compose", "warm", "InterpretationError"]


def __getattr__(name):          # lazy, so `python -m interpretation.interpret` runs cleanly
    if name in __all__:
        from . import interpret
        return getattr(interpret, name)
    raise AttributeError(name)
