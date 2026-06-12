"""Tests for EscalationChannel (E1/E2).

Local-first, no network: we use a tempfile inbox_dir and never set the Telegram
env vars, so `telegram_available()` is False and no HTTP is ever attempted. The
file backend is the source of truth — `ask()` writes the pending file and a reply
appears when a `<ask_id>.reply` file exists in the inbox dir.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentigent.operator.escalation_channel import (
    EscalationChannel,
    EscalationReply,
    EscalationRequest,
)


@pytest.fixture
def chan(tmp_path, monkeypatch):
    """An EscalationChannel rooted at a temp inbox with Telegram env explicitly cleared."""
    monkeypatch.delenv("SENTIGENT_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("SENTIGENT_TELEGRAM_CHAT_ID", raising=False)
    return EscalationChannel(inbox_dir=str(tmp_path / "escalations"))


def _req(ask_id="run1-step4"):
    return EscalationRequest(
        ask_id=ask_id,
        headline="Step 4/9: about to `supabase db push` to prod. Approve / skip / takeover?",
        options=["approve", "skip", "takeover"],
        context="diff: +12 -3 in migrations/0007.sql",
    )


def test_telegram_unavailable_without_env(chan):
    assert chan.telegram_available() is False


def test_ask_writes_pending_and_returns_true(chan, tmp_path):
    req = _req()
    assert chan.ask(req) is True

    pending = tmp_path / "escalations" / f"{req.ask_id}.pending.json"
    assert pending.exists()

    data = json.loads(pending.read_text(encoding="utf-8"))
    assert data["headline"] == req.headline
    assert data["options"] == req.options
    assert data["context"] == req.context
    assert data["ask_id"] == req.ask_id


def test_poll_returns_none_before_any_reply(chan):
    req = _req()
    chan.ask(req)
    assert chan.poll(req.ask_id, req.options) is None


def test_poll_matches_approve_after_reply_dropped(chan):
    req = _req()
    chan.ask(req)

    Path(chan.reply_path(req.ask_id)).write_text("approve\n", encoding="utf-8")

    reply = chan.poll(req.ask_id, req.options)
    assert isinstance(reply, EscalationReply)
    assert reply.ask_id == req.ask_id
    assert reply.decision == "approve"
    assert reply.raw == "approve\n"


def test_unmatched_reply_yields_empty_decision(chan):
    req = _req()
    chan.ask(req)

    Path(chan.reply_path(req.ask_id)).write_text("banana", encoding="utf-8")

    reply = chan.poll(req.ask_id, req.options)
    assert reply is not None
    assert reply.decision == ""
    assert reply.raw == "banana"


def test_substring_and_case_insensitive_match(chan):
    req = _req()
    chan.ask(req)

    Path(chan.reply_path(req.ask_id)).write_text("Let's TAKEOVER this one", encoding="utf-8")

    reply = chan.poll(req.ask_id, req.options)
    assert reply is not None
    assert reply.decision == "takeover"


def test_reply_path_is_under_inbox(chan, tmp_path):
    p = Path(chan.reply_path("abc-1"))
    assert p.parent == tmp_path / "escalations"
    assert p.name == "abc-1.reply"
