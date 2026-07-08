"""WS-B CORE ablation harness for the 2-Week Truth Sprint.

See ``docs/TRUTH-SPRINT-2WEEK.md`` (Workstream WS-B — SWE-bench Verified
harness + ablation arms). This package builds the ablation harness MECHANISM,
fully tested on a TOY task with NO Docker and NO network:

  - a task abstraction (temp repo dir + hidden pytest the patch must pass),
  - an arm runner (A0 = one-shot, no repair; A2 = bounded repair retry),
  - a pluggable SUT solver interface (real solver shells to ``claude -p``;
    tests inject a deterministic mock solver so they run offline),
  - a paired runner that appends result rows to a sprint-scoped results
    sqlite under ``~/.sentigent/`` (NEVER ``memory_hussain.db``).

This module is the importable package root; logic lands in sibling modules.
Additive only — sits alongside the existing
``sentigent/eval/sprint_grader.py``.
"""
