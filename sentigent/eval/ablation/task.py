"""Toy task abstraction for the WS-B CORE ablation harness.

An :class:`AblationTask` is a self-contained, Docker-free, network-free unit:
a temp repo dir holding a deliberately-broken Python function plus a HIDDEN
pytest test that the patch must pass. ``build_toy_task`` materializes one such
fixture; ``apply_patch`` writes a candidate patch into the broken file; and
``run_hidden_test`` runs the hidden test as a subprocess and returns pass/fail.

See docs/TRUTH-SPRINT-2WEEK.md (Workstream WS-B). Additive only.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

# A deliberately-broken implementation: add() subtracts instead of adding.
_BROKEN_SOURCE = '''"""Toy module under test (deliberately broken)."""


def add(a, b):
    return a - b
'''

# The correct implementation the SUT must converge on.
_GOOD_SOURCE = '''"""Toy module under test (patched)."""


def add(a, b):
    return a + b
'''

# HIDDEN pytest test — asserts the correct behavior of add().
_HIDDEN_TEST_SOURCE = '''from toy_module import add


def test_add_basic():
    assert add(2, 3) == 5


def test_add_zero():
    assert add(0, 0) == 0


def test_add_negative():
    assert add(-1, -2) == -3
'''


@dataclass
class AblationTask:
    """A single toy ablation task fixture.

    Attributes:
        task_id: stable identifier for the task.
        repo_dir: path to the materialized temp repo dir.
        broken_file: path to the broken source file (the patch target).
        hidden_test: path to the hidden pytest file.
        good_patch: the full correct source that resolves the hidden test.
    """

    task_id: str
    repo_dir: str
    broken_file: str
    hidden_test: str
    good_patch: str


def build_toy_task(base_dir: str | None = None) -> AblationTask:
    """Materialize a toy ablation task in a temp repo dir.

    Creates ``toy_module.py`` (deliberately broken ``add``) and a hidden
    ``test_hidden.py`` that asserts the correct behavior. When ``base_dir`` is
    None a fresh :func:`tempfile.mkdtemp` directory is used.
    """
    if base_dir is None:
        repo_dir = tempfile.mkdtemp(prefix="ablation_toy_")
    else:
        os.makedirs(base_dir, exist_ok=True)
        repo_dir = tempfile.mkdtemp(prefix="ablation_toy_", dir=base_dir)

    broken_file = os.path.join(repo_dir, "toy_module.py")
    hidden_test = os.path.join(repo_dir, "test_hidden.py")

    with open(broken_file, "w", encoding="utf-8") as fh:
        fh.write(_BROKEN_SOURCE)
    with open(hidden_test, "w", encoding="utf-8") as fh:
        fh.write(_HIDDEN_TEST_SOURCE)

    return AblationTask(
        task_id="toy_add",
        repo_dir=repo_dir,
        broken_file=broken_file,
        hidden_test=hidden_test,
        good_patch=_GOOD_SOURCE,
    )


def apply_patch(task: AblationTask, patch_text: str) -> None:
    """Write ``patch_text`` as the full new contents of the broken file."""
    with open(task.broken_file, "w", encoding="utf-8") as fh:
        fh.write(patch_text)


def run_hidden_test(task: AblationTask) -> bool:
    """Run the hidden pytest in the repo dir as a subprocess.

    NO network and NO Docker — a plain ``python3 -m pytest`` invocation scoped
    to the task's repo dir. Returns True iff the hidden test passes.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", task.hidden_test, "-q"],
        cwd=task.repo_dir,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0
