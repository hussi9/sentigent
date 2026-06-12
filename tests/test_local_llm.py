"""Tests for the local LLM client (Ollama-backed intelligence layer).

Network is always mocked — these lock behavior, not Ollama itself:
  - num_ctx is sent in the request options (prevents silent prompt truncation)
  - generate_json retries once on a malformed first response
  - generate_json gives up (returns None) when every attempt is unparseable
  - the {...} regex fallback recovers JSON wrapped in prose
"""
from __future__ import annotations

import json
from unittest import mock

from sentigent.intelligence import local_llm


def _fake_response(text: str):
    """A context-manager stand-in for urllib.request.urlopen()."""
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = json.dumps({"response": text}).encode()
    cm.__enter__.return_value.status = 200
    return cm


def test_generate_sends_num_ctx_in_options():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _fake_response("ok")

    with mock.patch.object(local_llm.urllib.request, "urlopen", fake_urlopen):
        local_llm.generate("hi", model="m", num_ctx=12345)

    assert captured["body"]["options"]["num_ctx"] == 12345


def test_generate_defaults_num_ctx():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode())
        return _fake_response("ok")

    with mock.patch.object(local_llm.urllib.request, "urlopen", fake_urlopen):
        local_llm.generate("hi", model="m")

    assert captured["body"]["options"]["num_ctx"] == local_llm.DEFAULT_NUM_CTX


def test_generate_json_retries_once_then_succeeds():
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        # First attempt: garbage. Second attempt: valid JSON.
        return _fake_response("not json" if calls["n"] == 1 else '{"ok": true}')

    with mock.patch.object(local_llm.urllib.request, "urlopen", fake_urlopen):
        out = local_llm.generate_json("p", model="m")

    assert out == {"ok": True}
    assert calls["n"] == 2  # retried exactly once


def test_generate_json_gives_up_after_retries():
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        return _fake_response("never valid json")

    with mock.patch.object(local_llm.urllib.request, "urlopen", fake_urlopen):
        out = local_llm.generate_json("p", model="m", retries=1)

    assert out is None
    assert calls["n"] == 2  # initial + 1 retry, then None


def test_generate_json_regex_fallback_extracts_object():
    def fake_urlopen(req, timeout=None):
        return _fake_response('Sure! Here you go: {"a": 1} hope that helps')

    with mock.patch.object(local_llm.urllib.request, "urlopen", fake_urlopen):
        out = local_llm.generate_json("p", model="m")

    assert out == {"a": 1}
