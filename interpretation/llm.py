"""LLM providers for node 01. Selected with env PATHOS_LLM = anthropic (default) | openai | ollama | stub.

Every provider exposes call(kind, system, user, tool_name, schema, timeout, context) -> dict, returning the
structured object (a turn or a score) unvalidated. Validation and retries live in interpret.py.

Env:
  PATHOS_LLM                  provider (default: anthropic)
  PATHOS_MODEL_ASK            model for next_turn   (anthropic default: claude-sonnet-5-5)
  PATHOS_MODEL_COMPOSE        model for compose     (anthropic default: claude-sonnet-5-5)
  PATHOS_EFFORT_ASK / _COMPOSE anthropic effort, low|medium|high (defaults: low / medium); thinking is off
  ANTHROPIC_API_KEY / OPENAI_API_KEY   as usual for those SDKs
  OLLAMA_HOST                 default http://127.0.0.1:11434

`stub` is offline and deterministic: generic probes and a template score chosen by simple cue matching. It exists so
the orchestrator and the eval harness can run without a key. It is not a composer.
"""
from __future__ import annotations

import copy
import json
import os
import re
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


def load_dotenv(path=None) -> None:
    """Read KEY=VALUE lines from <repo>/.env into os.environ (gitignored; holds ANTHROPIC_API_KEY).
    Never overrides a variable that is already set. No dependency on python-dotenv."""
    from pathlib import Path
    path = Path(path) if path else Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


class LLMTimeout(LLMError):
    pass


class LLMAuthError(LLMError):
    """Bad or missing key: retrying cannot help."""


ANTHROPIC_DEFAULTS = {"ask": "claude-sonnet-5-5", "compose": "claude-sonnet-5-5"}
TEMPERATURE = {"ask": 0.7, "compose": 0.6}          # openai / ollama only; current Anthropic SDKs have no temperature
EFFORT = {"ask": os.environ.get("PATHOS_EFFORT_ASK", "low"),           # Anthropic output_config.effort
          "compose": os.environ.get("PATHOS_EFFORT_COMPOSE", "medium")}
MAX_TOKENS = {"ask": 400, "compose": 1600}


def model_for(kind: str, provider: str) -> str:
    env = os.environ.get(f"PATHOS_MODEL_{kind.upper()}")
    if env:
        return env
    if provider == "anthropic":
        return ANTHROPIC_DEFAULTS[kind]
    if provider == "stub":
        return "stub"
    raise LLMError(f"set PATHOS_MODEL_{kind.upper()} for provider {provider}")


def inline_refs(schema: dict) -> dict:
    """Resolve local '#/$defs/...' refs and drop $schema/$id, so every provider sees one self-contained schema."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                target = walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
                rest = {k: walk(v) for k, v in node.items() if k != "$ref"}
                return {**target, **rest}
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "$schema", "$id")}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


COMBINATORS = ("allOf", "anyOf", "oneOf")
DEEP_DROP = COMBINATORS + ("if", "then", "else", "not", "prefixItems", "contains", "minContains", "maxContains")


def provider_schema(schema: dict, level: int = 1) -> dict:
    """The schema as sent to a provider's tool definition.
    level 1: drop top-level allOf/anyOf/oneOf (Anthropic rejects them; the contract uses them for per-diagram `at`
             and for `question` when asking).
    level 2: also drop every combinator, conditional and contains-rule at any depth.
    Nothing is lost: interpret.py validates every reply against the full contract schema and retries with the errors."""
    def deep(node):
        if isinstance(node, dict):
            return {k: deep(v) for k, v in node.items() if k not in DEEP_DROP}
        if isinstance(node, list):
            return [deep(x) for x in node]
        return node
    if level >= 2:
        return deep(schema)
    return {k: v for k, v in schema.items() if k not in COMBINATORS}


# ------------------------------------------------------------------ anthropic
class Anthropic:
    name = "anthropic"

    def __init__(self):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise LLMError("pip install anthropic") from e
        import anthropic
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY is not set: paste it into <repo>/.env (see .env.example)")
        self._sdk = anthropic
        self._client = anthropic.Anthropic(max_retries=0)
        self._unsupported: set = set()
        self._schema_level = 1
        self._thinking_off = 0          # index into THINKING_OFF

    # Ways to turn thinking off, tried in order: Sonnet 5.5 (the default) rejects "disabled" and wants "between_tools";
    # older models may reject "between_tools". If both are refused, `thinking` is omitted.
    THINKING_OFF = ({"type": "between_tools"}, {"type": "disabled"})

    def _create(self, kind, **kw):
        """messages.create with latency options (thinking off, effort). If the SDK or the model refuses one of them,
        fall back (next thinking-off form, or drop the option) for the rest of the process and retry."""
        a = self._sdk
        tools = kw.pop("tools")

        def send():
            optional = {"output_config": {"effort": EFFORT[kind]}}
            if self._thinking_off < len(self.THINKING_OFF):
                optional["thinking"] = self.THINKING_OFF[self._thinking_off]
            extras = {k: v for k, v in optional.items() if k not in self._unsupported}
            ts = [{**t, "input_schema": provider_schema(t["input_schema"], self._schema_level)} for t in tools]
            return self._client.messages.create(**kw, tools=ts, **extras)

        for _ in range(4):
            try:
                return send()
            except (TypeError, a.BadRequestError) as e:
                msg = str(e).lower()
                if "input_schema" in msg and self._schema_level < 2:
                    self._schema_level = 2
                elif "thinking" in msg and self._thinking_off < len(self.THINKING_OFF):
                    self._thinking_off += 1
                elif "output_config" not in self._unsupported and ("output_config" in msg or "effort" in msg):
                    self._unsupported.add("output_config")
                else:
                    raise
        return send()

    # Forced tool_choice ("tool"/"any") is a 400 on Sonnet 5.5 and later, so the tool is requested with "auto" plus
    # an instruction in the system prompt. A reply without a tool_use block raises LLMError, which interpret.py retries.
    TOOL_CHOICE = {"type": "auto", "disable_parallel_tool_use": True}

    @staticmethod
    def _system(system, tool_name):
        return [{"type": "text", "text": f"{system}\n\nRespond only by calling the `{tool_name}` tool, exactly once.",
                 "cache_control": {"type": "ephemeral"}}]

    def call(self, kind, system, user, tool_name, schema, timeout, context=None):
        a = self._sdk
        try:
            resp = self._create(
                kind,
                model=model_for(kind, self.name),
                max_tokens=MAX_TOKENS[kind],
                system=self._system(system, tool_name),
                messages=[{"role": "user", "content": user}],
                tools=[{"name": tool_name, "description": f"Return the {kind} result.", "input_schema": schema}],
                tool_choice=self.TOOL_CHOICE,
                timeout=timeout,
            )
        except a.APITimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except (a.AuthenticationError, a.PermissionDeniedError) as e:
            raise LLMAuthError(f"{type(e).__name__}: {e} (check ANTHROPIC_API_KEY in <repo>/.env)") from e
        except a.APIError as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        for block in resp.content:
            if block.type == "tool_use":
                return block.input
        raise LLMError(f"no tool_use block in response (stop_reason={getattr(resp, 'stop_reason', '?')})")

    def warm(self, kind, system, tool_name, schema):
        """Prime the prompt cache (system + tool) with a 1-token request. Best effort; errors are ignored."""
        try:
            self._create(
                kind, model=model_for(kind, self.name), max_tokens=1,
                system=self._system(system, tool_name),
                messages=[{"role": "user", "content": "warm-up"}],
                tools=[{"name": tool_name, "description": f"Return the {kind} result.", "input_schema": schema}],
                tool_choice=self.TOOL_CHOICE, timeout=15)
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ openai
class OpenAI:
    name = "openai"

    def __init__(self):
        try:
            import openai
        except ImportError as e:
            raise LLMError("pip install openai") from e
        self._sdk = openai
        self._client = openai.OpenAI(max_retries=0)

    def call(self, kind, system, user, tool_name, schema, timeout, context=None):
        o = self._sdk
        try:
            resp = self._client.chat.completions.create(
                model=model_for(kind, self.name),
                temperature=TEMPERATURE[kind],
                max_tokens=MAX_TOKENS[kind],
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": {"name": tool_name, "schema": schema, "strict": False}},
                timeout=timeout,
            )
        except o.APITimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except o.APIError as e:
            raise LLMError(f"{type(e).__name__}: {e}") from e
        try:
            return json.loads(resp.choices[0].message.content)
        except (TypeError, ValueError) as e:
            raise LLMError(f"unparseable JSON: {e}") from e


# ------------------------------------------------------------------ ollama
class Ollama:
    name = "ollama"

    def call(self, kind, system, user, tool_name, schema, timeout, context=None):
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        body = json.dumps({
            "model": model_for(kind, self.name), "stream": False, "format": schema,
            "options": {"temperature": TEMPERATURE[kind]},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(f"{host}/api/chat", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
        except TimeoutError as e:
            raise LLMTimeout(str(e)) from e
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), TimeoutError):
                raise LLMTimeout(str(e)) from e
            raise LLMError(str(e)) from e
        try:
            return json.loads(data["message"]["content"])
        except (KeyError, TypeError, ValueError) as e:
            raise LLMError(f"unparseable JSON: {e}") from e


# ------------------------------------------------------------------ stub (offline, deterministic)
class Stub:
    """Plumbing only: generic probes, cue-matched template scores. Never use its output to judge the questions."""
    name = "stub"

    def call(self, kind, system, user, tool_name, schema, timeout, context=None):
        from . import prompts
        dialogue = context["dialogue"]
        guess = self._guess(dialogue, prompts)
        if kind == "ask":
            n = len(dialogue["exchanges"])
            ok = [e["answer"] for e in dialogue["exchanges"] if e["status"] == "ok"]
            guarded = len(ok) < n or sum(len(a.split()) for a in ok) / max(1, len(ok)) < 4
            if n >= (3 if guarded else 2):       # prompt policy: default 2, a third only for guarded answers
                return {"action": "compose", "planned_questions": n, "hypothesis": {**guess, "confidence": "medium", "unknown": "nothing essential"}}
            probes = prompts.lang_block(dialogue.get("lang"))["probes"]
            return {"action": "ask", "question": probes[min(n - 1, len(probes) - 1)], "planned_questions": 3 if guarded else 2,
                    "hypothesis": {**guess, "confidence": "low", "unknown": "stub: generic probe"}}
        return self._score(dialogue, guess, prompts)

    @staticmethod
    def _guess(dialogue, prompts):
        fw = prompts.framework()
        answers = [e["answer"] for e in dialogue["exchanges"] if e["status"] == "ok"]
        text = " ".join(answers).lower()
        best = ("mystery-engage", "longing", 0)
        for did, a in fw["active"].items():
            for pos, p in a["positions"].items():
                hits = sum(1 for c in p["cues"] if c.lower() in text)
                if hits > best[2]:
                    best = (did, pos, hits)
        did, pos, _ = best
        mirror = fw["active"][did]["positions"][pos]["emotions"][0]
        for b in fw["bridges"]["entries"]:
            if any(re.search(rf"\b{re.escape(w)}\b", text) for w in b["words"]):
                mirror = b["toward"][0]
                break
        traj = "hold"
        for pat, t in [(r"go away|stop|calm|rest|quiet", "dissolve"), (r"let it out|scream|cry", "release"),
                       (r"\bmore\b|alive", "amplify"), (r"move on|turn it into", "transmute")]:
            if re.search(pat, text):
                traj = t
                break
        words = sum(len(a.split()) for a in answers) / max(1, len(answers))
        length = "brief" if words < 4 else "long" if words > 25 else "medium"
        return {"diagram": did, "at": pos, "mirror_emotion": mirror, "trajectory": traj, "length": length}

    @staticmethod
    def _score(dialogue, g, prompts):
        fw = prompts.framework()
        did, pos, traj = g["diagram"], g["at"], g["trajectory"]
        lv = prompts.positions()[did]
        nb = prompts.neighbours()[did][pos]
        if traj == "hold" or not nb:
            end = pos
        elif did == "mystery-engage":
            pick = {"dissolve": max, "release": max, "amplify": min}.get(traj)
            end = pick(nb, key=lambda p: lv[p]) if pick else nb[0]
        else:
            end = (min if traj == "dissolve" else max)(nb, key=lambda p: lv[p])
        emos = fw["active"][did]["positions"][pos]["emotions"]
        mix = [g["mirror_emotion"]] + [e for e in emos if e != g["mirror_emotion"]][:2]
        hb = lambda t, r, w: {"tempo": t, "regularity": r, "weight": w}
        ch = lambda reg, col, den, br: {"register": reg, "color": col, "density": den, "brightness": br}
        moves = [
            {"phase": "mirror", "at": pos, "span": "medium", "heartbeat": hb("resting", "uneven", "present"),
             "chord": ch("mid", ["min3", "p5", "maj2"], "medium", "veiled"), "transition": "glide"},
            {"phase": "dwell", "at": pos, "span": "long", "heartbeat": hb("slow", "steady", "present"),
             "chord": ch("low", ["min3", "p5"], "sparse", "dark"), "transition": "slow_glide"},
            {"phase": "resurface", "at": end, "span": "medium", "heartbeat": hb("resting", "steady", "faint"),
             "chord": ch("mid", ["p5", "maj6"], "sparse", "clear"), "transition": "slow_glide"},
        ]
        last = [e["answer"] for e in dialogue["exchanges"] if e["status"] == "ok"]
        score = {
            "contract_version": "0.3", "diagram": did, "mirror_emotion": g["mirror_emotion"],
            "mixture": [{"emotion": e, "weight": w} for e, w in zip(mix, (0.7, 0.45, 0.3))],
            "tension": "stub score: template, not composed", "intention": (last[-1][:200] if last else "to be accompanied"),
            "intention_source": "inferred", "trajectory": traj, "length": g["length"], "movements": moves, "title": "stub",
        }
        if traj != "hold":
            dest = [e for e in fw["active"][did]["positions"][end]["emotions"]][:2]
            score["destination"] = [{"emotion": e, "weight": w} for e, w in zip(dest, (0.6, 0.4))]
        return score


PROVIDERS = {"anthropic": Anthropic, "openai": OpenAI, "ollama": Ollama, "stub": Stub}
_cache: dict = {}


def get_provider(name: str | None = None):
    load_dotenv()
    name = (name or os.environ.get("PATHOS_LLM") or "anthropic").lower()
    if name not in PROVIDERS:
        raise LLMError(f"unknown PATHOS_LLM={name}; one of {sorted(PROVIDERS)}")
    if name not in _cache:
        _cache[name] = PROVIDERS[name]()
    return _cache[name]
