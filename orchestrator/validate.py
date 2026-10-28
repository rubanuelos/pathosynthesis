"""Validation against contract v0.3.

validate_score()    schema (contract/score.schema.json) + semantic_errors(). Any failure -> ScoreError,
                    and the session plays a fallback score. No partial repair (contract §3.3).
semantic_errors()   the rules the schema cannot express. Must stay identical to
                    `semantic_errors` in contract/check_contract.py (tests/test_validate.py compares
                    the two whenever check_contract.py is importable).
validate_turn()     contract/turn.schema.json. Invalid turn -> treated like an interpretation error.
validate_dialogue() contract/dialogue.schema.json (turns resolved through the registry).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contract"
CONTRACT_VERSION = "0.3"


class ContractError(ValueError):
    """Something does not satisfy the contract. `.errors` lists every problem."""

    kind = "document"

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__(f"invalid {self.kind}:\n  - " + "\n  - ".join(self.errors))


class ScoreError(ContractError):
    kind = "score"


class TurnError(ContractError):
    kind = "turn"


class DialogueError(ContractError):
    kind = "dialogue"


def _load(name: str) -> dict:
    return json.loads((CONTRACT_DIR / name).read_text())


@lru_cache(maxsize=1)
def _validators() -> dict[str, Draft202012Validator]:
    schemas = {n: _load(f"{n}.schema.json") for n in ("score", "turn", "dialogue")}
    registry = Registry().with_resources(
        (s["$id"], Resource.from_contents(s)) for s in schemas.values() if "$id" in s
    )
    out = {}
    for n, s in schemas.items():
        Draft202012Validator.check_schema(s)
        out[n] = Draft202012Validator(s, registry=registry)
    return out


def _schema_errors(kind: str, doc: object) -> list[str]:
    errs = sorted(_validators()[kind].iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errs]


def semantic_errors(score: dict) -> list[str]:
    """Contract §3.3 rules beyond the schema. Assumes the schema already passed."""
    errors: list[str] = []
    phases = [m["phase"] for m in score["movements"]]
    if len(phases) < 2 or phases[1] != "dwell":
        errors.append(f"movements/1: second movement must be 'dwell', got {phases[1:2]}")
    if phases[-1] != "resurface":
        errors.append(f"movements/{len(phases) - 1}: last movement must be 'resurface', got '{phases[-1]}'")
    names = [e["emotion"] for e in score["mixture"]]
    if score["mirror_emotion"] not in names:
        errors.append(f"mirror_emotion: '{score['mirror_emotion']}' is not in mixture {names}")
    for field in ("mixture", "destination"):
        seen: set[str] = set()
        for i, e in enumerate(score.get(field, [])):
            if e["emotion"] in seen:
                errors.append(f"{field}/{i}: '{e['emotion']}' appears twice")
            seen.add(e["emotion"])
    return errors


def validate_score(score: object) -> dict:
    errs = _schema_errors("score", score)
    if not errs:
        errs = semantic_errors(score)  # type: ignore[arg-type]
    if errs:
        raise ScoreError(errs)
    return score  # type: ignore[return-value]


def validate_turn(turn: object) -> dict:
    errs = _schema_errors("turn", turn)
    if errs:
        raise TurnError(errs)
    return turn  # type: ignore[return-value]


def validate_dialogue(dialogue: object) -> dict:
    errs = _schema_errors("dialogue", dialogue)
    if errs:
        raise DialogueError(errs)
    return dialogue  # type: ignore[return-value]


def load_json(path: str | Path, kind: str = "score") -> dict:
    """Read a JSON file. Unparseable files raise the matching ContractError."""
    err = {"score": ScoreError, "turn": TurnError, "dialogue": DialogueError}[kind]
    try:
        return json.loads(Path(path).read_text())
    except json.JSONDecodeError as e:
        raise err([f"{path}: not JSON: {e}"]) from e


def load_score(path: str | Path) -> dict:
    return validate_score(load_json(path, "score"))
