"""Local LLM client — Ollama-backed, model-agnostic, local-first.

The home for sentigent's INTELLIGENCE tasks (profile synthesis, outcome
labeling, the in-loop judge). Never used on the hot path.

Switching models is one env var — no code change:
    SENTIGENT_LLM_MODEL=llama3:8b      # default, present today
    SENTIGENT_LLM_MODEL=gemma3:27b     # flip to Gemma when pulled
    SENTIGENT_OLLAMA_URL=http://...    # default http://localhost:11434

Zero third-party deps (urllib only). Fail-soft: callers must handle None /
llm_available()==False. See docs/plans/2026-06-03-operator-autopilot-design.md.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional

OLLAMA_URL = os.environ.get("SENTIGENT_OLLAMA_URL", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("SENTIGENT_LLM_MODEL", "llama3:8b")


def active_model() -> str:
    """The model the intelligence layer will use (env-driven, swappable)."""
    return os.environ.get("SENTIGENT_LLM_MODEL", DEFAULT_MODEL)


def resolver_model(available: Optional[list[str]] = None) -> str:
    """Model for the Clone Resolver (the escalation-answering organ).

    The whole point of the resolver is to answer a blocker AS the user — that
    judgment quality matters, so it prefers Gemma. Selection order:
      1. SENTIGENT_RESOLVER_MODEL env override (explicit wins).
      2. The largest pulled gemma3:* (27b > 12b > 4b > 1b by tag number).
      3. Fall back to active_model() (e.g. llama3:8b) so the resolver still runs
         when no Gemma is present.

    `available` lets callers pass a pre-fetched model list (avoids a second HTTP
    round-trip); when omitted it probes Ollama via list_models()."""
    env = os.environ.get("SENTIGENT_RESOLVER_MODEL")
    if env:
        return env
    models = available if available is not None else list_models()
    gemmas = [m for m in models if m.startswith("gemma3:")]
    if gemmas:
        def _size(name: str) -> float:
            tag = name.split(":", 1)[1] if ":" in name else ""
            m = re.match(r"([\d.]+)\s*b", tag.lower())
            return float(m.group(1)) if m else 0.0
        return max(gemmas, key=_size)
    return active_model()


def llm_available(timeout: float = 2.0) -> bool:
    """True if the local Ollama server is reachable. Cheap, fail-soft."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as r:
            return getattr(r, "status", 200) == 200
    except Exception:
        return False


def list_models(timeout: float = 3.0) -> list[str]:
    """Names of locally-pulled models (so callers can see if Gemma is present)."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as r:
            data = json.loads(r.read().decode())
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


# Context window must hold the whole prompt + the generated answer. The default
# (often 4096) silently truncates our ~8KB CLAUDE.md prompt, which corrupts JSON
# output on smaller models (e.g. gemma3:4b). 8192 fits prompt+answer with headroom.
DEFAULT_NUM_CTX = int(os.environ.get("SENTIGENT_LLM_NUM_CTX", "8192"))


def generate(
    prompt: str,
    *,
    model: Optional[str] = None,
    system: Optional[str] = None,
    json_mode: bool = False,
    timeout: float = 180.0,
    num_ctx: Optional[int] = None,
) -> str:
    """Single-shot completion via Ollama /api/generate. Returns the raw text
    (empty string on any failure — caller decides what to do)."""
    body: dict = {
        "model": model or active_model(),
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx or DEFAULT_NUM_CTX},
    }
    if system:
        body["system"] = system
    if json_mode:
        body["format"] = "json"
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read().decode())
        return resp.get("response", "") or ""
    except Exception:
        return ""


def _parse_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None
        return None


def generate_json(
    prompt: str,
    *,
    model: Optional[str] = None,
    system: Optional[str] = None,
    timeout: float = 180.0,
    num_ctx: Optional[int] = None,
    retries: int = 1,
) -> Optional[dict]:
    """Completion forced to JSON. Returns a dict, or None if the model didn't
    produce parseable JSON (falls back to extracting the first {...} block).

    Smaller local models (e.g. gemma3:4b) occasionally emit malformed JSON on a
    long structured prompt; one cheap retry recovers most of those misses."""
    for _ in range(max(1, retries + 1)):
        raw = generate(
            prompt, model=model, system=system, json_mode=True,
            timeout=timeout, num_ctx=num_ctx,
        )
        obj = _parse_json(raw)
        if obj is not None:
            return obj
    return None
