"""Pluggable SUT solver interface for the WS-B CORE ablation harness.

A :class:`Solver` takes an :class:`~sentigent.eval.ablation.task.AblationTask`
(plus optional ``feedback`` from a prior failed attempt) and returns patch text
(the full new contents of the broken file).

Two implementations ship here:

  - :class:`MockSolver` — a deterministic, offline solver that returns scripted
    patch strings in sequence. Unit tests inject this so they run with NO
    network and NO Docker.
  - :class:`ClaudeSubscriptionSolver` — the REAL solver that shells to
    ``claude -p`` via subprocess. It MUST NOT set ``ANTHROPIC_API_KEY`` so the
    CLI uses the Claude subscription (not the metered API). The
    :func:`_subprocess_env` helper builds that scrubbed environment.

See docs/TRUTH-SPRINT-2WEEK.md (Workstream WS-B). Additive only.
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod

from sentigent.eval.ablation.task import AblationTask


class Solver(ABC):
    """Abstract SUT solver: produce patch text for a task."""

    @abstractmethod
    def solve(self, task: AblationTask, feedback: str | None = None) -> str:
        """Return patch text (full new contents of the broken file).

        Args:
            task: the ablation task to solve.
            feedback: optional context from a prior failed attempt (e.g. the
                hidden-test failure output) so a repair arm can do better.
        """
        raise NotImplementedError


class MockSolver(Solver):
    """Deterministic offline solver returning scripted patches in order.

    Each call to :meth:`solve` returns the next patch string from ``patches``.
    Once exhausted, it keeps returning the final patch (so an A0 one-shot and an
    A2 repair arm can share the same scripted solver without index errors).
    Tracks how many times it was called via :attr:`calls`.
    """

    def __init__(self, patches: list[str]):
        if not patches:
            raise ValueError("MockSolver requires at least one scripted patch")
        self._patches = list(patches)
        self.calls = 0

    def solve(self, task: AblationTask, feedback: str | None = None) -> str:
        idx = min(self.calls, len(self._patches) - 1)
        patch = self._patches[idx]
        self.calls += 1
        return patch


def _subprocess_env() -> dict:
    """Copy ``os.environ`` but REMOVE ``ANTHROPIC_API_KEY``.

    The real solver shells to ``claude -p``; dropping the API key forces the
    CLI onto the Claude subscription (not the metered API), which is the whole
    point of the truth sprint's $0-metered constraint.
    """
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


class ClaudeSubscriptionSolver(Solver):
    """Real solver: shells to ``claude -p`` on the Claude subscription.

    NEVER sets ``ANTHROPIC_API_KEY`` (see :func:`_subprocess_env`). Builds a
    prompt asking for the full corrected file contents, runs ``claude -p`` in
    the task's repo dir, and returns the raw stdout as patch text.
    """

    def __init__(self, claude_bin: str = "claude", timeout: int = 600):
        self.claude_bin = claude_bin
        self.timeout = timeout

    def _build_prompt(self, task: AblationTask, feedback: str | None) -> str:
        with open(task.broken_file, "r", encoding="utf-8") as fh:
            current = fh.read()
        prompt = (
            "You are fixing a deliberately-broken Python file so it passes a "
            "hidden test suite. Return ONLY the full corrected contents of the "
            f"file `{os.path.basename(task.broken_file)}` — no markdown fences, "
            "no commentary.\n\n"
            f"Current contents:\n{current}"
        )
        if feedback:
            prompt += f"\n\nThe previous attempt failed with:\n{feedback}"
        return prompt

    def solve(self, task: AblationTask, feedback: str | None = None) -> str:
        prompt = self._build_prompt(task, feedback)
        proc = subprocess.run(
            [self.claude_bin, "-p", prompt],
            cwd=task.repo_dir,
            capture_output=True,
            text=True,
            env=_subprocess_env(),
            timeout=self.timeout,
        )
        return proc.stdout
