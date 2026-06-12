"""EscalationChannel (E1) + ApprovalInbox (E2) — reach the human, get the answer.

While `escalation.py`'s EscalationDecider answers *whether* to wake you, this is the
*transport*: it pushes the decision-ready question to you and receives your reply.
This is the ONLY thing that reaches you when you're away from the desk during Fly mode.

Two backends, auto-selected and fail-soft:
  - Telegram Bot API (direct, urllib only) — if SENTIGENT_TELEGRAM_TOKEN +
    SENTIGENT_TELEGRAM_CHAT_ID are set. Best-effort, short timeouts, never raises.
  - Local file inbox (always available) — `ask()` writes a `<ask_id>.pending.json`
    and a reply appears when a `<ask_id>.reply` file is dropped in the inbox dir.
    The file backend is the source of truth (and is what tests exercise with no token).

Local-first principle: the file backend works (and is testable) with no network at all.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_HTTP_TIMEOUT = 5.0  # seconds — short; the loop must not hang on the network


@dataclass
class EscalationRequest:
    ask_id: str            # caller-supplied unique id (e.g. f"{run_id}-{step_id}")
    headline: str          # the one-line decision shown to the user
    options: list[str]     # e.g. ["approve", "skip", "takeover"]
    context: str = ""      # extra detail (diff/risk)


@dataclass
class EscalationReply:
    ask_id: str
    decision: str          # normalized to one of options (lowercased), or "" if unmatched
    raw: str


def _normalize(text: str, options: list[str]) -> str:
    """Match a freeform reply against the allowed options (case-insensitive substring).

    First tries an exact first-word match, then a substring scan over the whole text.
    Returns the matched option lowercased, or "" if nothing matches.
    """
    if not text or not options:
        return ""
    low_opts = [o.lower() for o in options]
    lowered = text.strip().lower()

    # 1) exact match on the first whitespace-delimited word (the common case: "approve\n")
    first = lowered.split()[0] if lowered.split() else ""
    if first in low_opts:
        return first

    # 2) substring scan — the reply *contains* an option (e.g. "let's approve this")
    for opt in low_opts:
        if opt and opt in lowered:
            return opt

    return ""


class EscalationChannel:
    """Sends an escalation and polls for the answer.

    Telegram (if token+chat_id present) AND a local file inbox (always on). `ask()`
    always writes the pending file so the run is recoverable even if Telegram is down.
    """

    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        inbox_dir: str | None = None,
    ) -> None:
        self.token = token if token is not None else os.environ.get("SENTIGENT_TELEGRAM_TOKEN")
        self.chat_id = (
            chat_id if chat_id is not None else os.environ.get("SENTIGENT_TELEGRAM_CHAT_ID")
        )
        if inbox_dir is None:
            inbox_dir = os.path.join(os.path.expanduser("~"), ".sentigent", "escalations")
        self.inbox_dir = Path(inbox_dir)

    # ── backend availability ─────────────────────────────────────────────────
    def telegram_available(self) -> bool:
        """True only when both token and chat id are present (non-empty)."""
        return bool(self.token) and bool(self.chat_id)

    # ── paths ────────────────────────────────────────────────────────────────
    def _pending_path(self, ask_id: str) -> Path:
        return self.inbox_dir / f"{ask_id}.pending.json"

    def reply_path(self, ask_id: str) -> str:
        """The file path a manual/UI reply can be dropped at."""
        return str(self.inbox_dir / f"{ask_id}.reply")

    # ── send ─────────────────────────────────────────────────────────────────
    def ask(self, req: EscalationRequest) -> bool:
        """Deliver the escalation.

        ALWAYS writes the pending file (source of truth for the run + tests). If
        Telegram is configured, also best-effort sends a message. Returns True if
        delivered to at least one backend — the file write practically always
        succeeds, so this returns True unless even the local filesystem fails.
        Fail-soft: never raises.
        """
        file_ok = self._write_pending(req)
        tg_ok = self._send_telegram(req) if self.telegram_available() else False
        return bool(file_ok or tg_ok)

    def _write_pending(self, req: EscalationRequest) -> bool:
        try:
            self.inbox_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "ask_id": req.ask_id,
                "headline": req.headline,
                "options": list(req.options),
                "context": req.context,
            }
            tmp = self._pending_path(req.ask_id).with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._pending_path(req.ask_id))  # atomic-ish swap
            return True
        except Exception:
            return False

    def _send_telegram(self, req: EscalationRequest) -> bool:
        try:
            opts = " / ".join(req.options)
            lines = [req.headline]
            if req.context:
                lines.append("")
                lines.append(req.context)
            lines.append("")
            lines.append(f"Reply with: {opts}")
            text = "\n".join(lines)
            return self._tg_post(
                "sendMessage",
                {"chat_id": self.chat_id, "text": text},
            ) is not None
        except Exception:
            return False

    # ── poll ─────────────────────────────────────────────────────────────────
    def poll(self, ask_id: str, options: list[str]) -> EscalationReply | None:
        """Check for an answer. Returns None if nothing has arrived yet.

        Order: (1) local `<ask_id>.reply` file (source of truth), then (2) Telegram
        getUpdates if configured. The decision is normalized to a matching option
        (case-insensitive), else `decision=""` for an unmatched reply.
        """
        # 1) file inbox
        raw = self._read_reply_file(ask_id)
        if raw is not None:
            return EscalationReply(ask_id=ask_id, decision=_normalize(raw, options), raw=raw)

        # 2) telegram
        if self.telegram_available():
            raw = self._poll_telegram(options)
            if raw is not None:
                return EscalationReply(
                    ask_id=ask_id, decision=_normalize(raw, options), raw=raw
                )

        return None

    def _read_reply_file(self, ask_id: str) -> str | None:
        try:
            p = Path(self.reply_path(ask_id))
            if not p.exists():
                return None
            return p.read_text(encoding="utf-8")
        except Exception:
            return None

    def _poll_telegram(self, options: list[str]) -> str | None:
        """Pull recent updates and return the first message text that contains an option."""
        try:
            data = self._tg_post("getUpdates", {"timeout": 0})
            if not data or not data.get("ok"):
                return None
            for upd in data.get("result", []):
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text", "")
                if text and _normalize(text, options):
                    return text
            return None
        except Exception:
            return None

    # ── telegram transport (urllib only, fail-soft) ──────────────────────────
    def _tg_post(self, method: str, params: dict) -> dict | None:
        try:
            url = _TELEGRAM_API.format(token=self.token, method=method)
            body = urllib.parse.urlencode(params).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST")
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
