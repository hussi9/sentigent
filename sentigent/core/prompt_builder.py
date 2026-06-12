"""Active prompt builder — guides users through template-based prompt construction.

Users call this to build well-structured prompts interactively.
Sentigent asks clarifying questions, fills a template, and returns a
copy-paste-ready prompt that captures all the context an AI needs.

Usage via MCP:
    sentigent_prompt_build(action="list")
        → list all available templates

    sentigent_prompt_build(action="start", template="product_spec")
        → begin a new session, returns first question

    sentigent_prompt_build(action="answer", session_id="abc123", answer="My SaaS app")
        → answer the current question, returns next question or completed prompt

    sentigent_prompt_build(action="status", session_id="abc123")
        → see current session state and remaining questions

    sentigent_prompt_build(action="abandon", session_id="abc123")
        → cancel the session

Also integrated into evaluate(): if a task prompt is detected as vague,
the Decision.metadata will include a 'prompt_suggestion' key pointing here.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ── Template data model ────────────────────────────────────────────────────────


@dataclass
class TemplateField:
    """One question/field in a prompt template."""
    name: str
    question: str
    placeholder: str
    required: bool = True
    hint: str = ""
    example: str = ""


@dataclass
class BuilderSession:
    """Active prompt-building session."""
    session_id: str
    template_name: str
    answers: dict[str, str]
    current_field_index: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    profile: str = "default"


# ── Template definitions ───────────────────────────────────────────────────────


def _product_spec_assemble(a: dict[str, str]) -> str:
    return f"""# Product Specification: {a.get('name', '—')}

## Problem Statement
{a.get('problem', '—')}

## Target Users
{a.get('users', '—')}

## Core Requirements
{a.get('requirements', '—')}

## Success Criteria
{a.get('success_criteria', '—')}

## Out of Scope
{a.get('out_of_scope', 'Not defined')}

## Technical Constraints
{a.get('constraints', 'None specified')}

---
*Please review this spec, identify any ambiguities, suggest edge cases to handle,
and flag anything that seems technically risky or underspecified.*"""


def _pr_review_assemble(a: dict[str, str]) -> str:
    return f"""# Code Review Request

## What Changed
{a.get('what_changed', '—')}

## PR / Branch
{a.get('pr_ref', '—')}

## Review Focus
{a.get('review_focus', 'General quality')}

## Context & Background
{a.get('context', '—')}

## Acceptance Criteria
{a.get('acceptance_criteria', '—')}

---
*Please review this change. Focus specifically on the areas listed above.
Flag any bugs, security issues, performance concerns, or missing tests.
Suggest specific improvements with code examples where relevant.*"""


def _bug_report_assemble(a: dict[str, str]) -> str:
    return f"""# Bug Report

## Summary
{a.get('summary', '—')}

## Steps to Reproduce
{a.get('steps', '—')}

## Expected Behavior
{a.get('expected', '—')}

## Actual Behavior
{a.get('actual', '—')}

## Environment
{a.get('environment', '—')}

## Logs / Error Messages
{a.get('logs', 'None provided')}

---
*Analyze this bug report. Identify the most likely root cause, suggest where
to look in the codebase, and propose a fix with code changes.*"""


def _refactor_assemble(a: dict[str, str]) -> str:
    return f"""# Refactoring Request

## Target: {a.get('target', '—')}

## Current Problems
{a.get('problems', '—')}

## Refactoring Goals
{a.get('goals', '—')}

## Constraints
{a.get('constraints', 'None — full freedom')}

## Test Requirements
{a.get('test_requirements', 'All existing tests must keep passing')}

---
*Refactor the code above according to the stated goals and constraints.
Show the before and after, explain each change, and confirm all test requirements are met.*"""


def _adr_assemble(a: dict[str, str]) -> str:
    return f"""# Architecture Decision Record: {a.get('title', '—')}

## Context
{a.get('context', '—')}

## Options Considered
{a.get('options', '—')}

## Decision
{a.get('decision', '—')}

## Rationale
{a.get('rationale', '—')}

## Consequences & Trade-offs
{a.get('consequences', '—')}

---
*Review this ADR. Identify any risks I may have missed, suggest any options
I haven't considered, and flag any long-term maintenance or scaling concerns.*"""


def _api_design_assemble(a: dict[str, str]) -> str:
    return f"""# API Design: {a.get('endpoint_name', '—')}

## Purpose
{a.get('purpose', '—')}

## HTTP Method & Path
{a.get('method_path', '—')}

## Authentication
{a.get('auth', '—')}

## Request Format
{a.get('request_format', '—')}

## Response Format
{a.get('response_format', '—')}

## Error Cases
{a.get('error_cases', '—')}

---
*Design the implementation for this API endpoint. Include:
request/response schemas, validation rules, error handling, auth middleware,
database queries, and any edge cases to handle.*"""


def _task_breakdown_assemble(a: dict[str, str]) -> str:
    return f"""# Task Breakdown Request

## Goal
{a.get('goal', '—')}

## Current State
{a.get('current_state', '—')}

## Constraints & Deadlines
{a.get('constraints', 'None')}

## Tech Stack
{a.get('tech_stack', '—')}

## Definition of Done
{a.get('done_criteria', '—')}

---
*Break this goal down into a concrete, ordered list of tasks.
For each task: estimate effort (S/M/L), identify dependencies, and flag any blockers.
Start with the minimum viable path to get something working.*"""


# ── Template registry ──────────────────────────────────────────────────────────


# ── Template → Claude Code skill mapping ──────────────────────────────────────
# Each template maps to the skill best suited to execute the assembled prompt.
# These match the skill names registered in Claude Code's skills system.
TEMPLATE_SKILL_MAP: dict[str, str] = {
    "product_spec":           "feature-dev:feature-dev",
    "pr_review":              "code-review:code-review",
    "bug_report":             "debug",
    "code_refactor":          "refactor",
    "architecture_decision":  "docs",
    "api_design":             "feature-dev:feature-dev",
    "task_breakdown":         "feature-dev:feature-dev",
}


_TEMPLATES: dict[str, dict[str, Any]] = {
    "product_spec": {
        "description": "Product / feature requirements document",
        "skill": "feature-dev:feature-dev",
        "fields": [
            TemplateField("name", "What is the product or feature name?",
                          "e.g. User authentication module",
                          hint="Keep it concise — one line"),
            TemplateField("problem", "What problem does it solve? Who has this problem?",
                          "e.g. Users forget passwords and can't recover them without IT help",
                          hint="Be specific — vague problems lead to vague solutions"),
            TemplateField("users", "Who are the target users? Describe their context.",
                          "e.g. Non-technical employees at SMBs, 50–500 person companies",
                          hint="Include skill level, frequency of use, main pain points"),
            TemplateField("requirements", "List the core functional requirements (one per line).",
                          "e.g. \n1. Users can reset password via email link\n2. Link expires after 30 minutes",
                          hint="Number them — makes gaps obvious"),
            TemplateField("success_criteria", "How will you know it's done? What metrics define success?",
                          "e.g. 95% of users can reset their own password without IT support",
                          hint="Measurable beats aspirational"),
            TemplateField("out_of_scope", "What is explicitly NOT included in this version?",
                          "e.g. SSO, biometric login, admin password override",
                          required=False,
                          hint="Saves arguments later"),
            TemplateField("constraints", "Any technical constraints or non-negotiables?",
                          "e.g. Must use existing PostgreSQL DB, no new third-party auth services",
                          required=False),
        ],
        "assembler": _product_spec_assemble,
    },
    "pr_review": {
        "description": "Code review — give reviewers the context they need",
        "skill": "code-review:code-review",
        "fields": [
            TemplateField("what_changed", "What does this PR change? Give a plain-English summary.",
                          "e.g. Adds rate limiting to the /api/login endpoint"),
            TemplateField("pr_ref", "PR number, branch name, or repo URL?",
                          "e.g. PR #342 in github.com/myorg/api",
                          required=False),
            TemplateField("review_focus", "What should reviewers focus on?",
                          "e.g. Security implications of the new auth flow, edge cases in retry logic",
                          hint="Be specific — 'general feedback' wastes everyone's time"),
            TemplateField("context", "What's the background? Why was this change needed?",
                          "e.g. We saw 3 brute-force login attempts last month"),
            TemplateField("acceptance_criteria", "What must be true before this merges?",
                          "e.g. All existing auth tests pass, new tests for rate limit added, no new lint errors"),
        ],
        "assembler": _pr_review_assemble,
    },
    "bug_report": {
        "description": "Bug report — everything needed to reproduce and fix",
        "skill": "debug",
        "fields": [
            TemplateField("summary", "One-line summary: what is broken?",
                          "e.g. Checkout fails silently when cart has >10 items"),
            TemplateField("steps", "Steps to reproduce (numbered list).",
                          "e.g. \n1. Add 11+ items to cart\n2. Click checkout\n3. See blank page with no error",
                          hint="If you can't reproduce it reliably, say so"),
            TemplateField("expected", "What should happen?",
                          "e.g. Order confirmation page or a clear error message"),
            TemplateField("actual", "What actually happens?",
                          "e.g. Blank white page, HTTP 500 in console, no order in DB"),
            TemplateField("environment", "Where does this happen? Browser, OS, version, env?",
                          "e.g. Chrome 120, macOS 14, production only (not staging)"),
            TemplateField("logs", "Paste any relevant error logs or stack traces.",
                          "e.g. TypeError: Cannot read properties of undefined (reading 'total')",
                          required=False),
        ],
        "assembler": _bug_report_assemble,
    },
    "code_refactor": {
        "description": "Refactoring request — scope, goals, and constraints",
        "skill": "refactor",
        "fields": [
            TemplateField("target", "Which file, module, or component needs refactoring?",
                          "e.g. sentigent/core/engine.py — evaluate() method"),
            TemplateField("problems", "What's wrong with the current code? Be specific.",
                          "e.g. \n- 300-line method that's hard to test\n- Mixes business logic with DB calls\n- No error handling"),
            TemplateField("goals", "What should the refactored code achieve?",
                          "e.g. Each function under 30 lines, unit-testable without DB, clear separation of concerns"),
            TemplateField("constraints", "What must NOT change? What are you not allowed to touch?",
                          "e.g. Public API must stay identical, no new dependencies",
                          required=False),
            TemplateField("test_requirements", "What test coverage is required?",
                          "e.g. All existing 47 tests must pass, add tests for the 3 new helper functions",
                          required=False),
        ],
        "assembler": _refactor_assemble,
    },
    "architecture_decision": {
        "description": "Architecture Decision Record (ADR) — capture a key technical choice",
        "skill": "docs",
        "fields": [
            TemplateField("title", "What decision are you making? (short title)",
                          "e.g. Choose message queue for async job processing"),
            TemplateField("context", "What's driving this decision? What problem are you solving?",
                          "e.g. Synchronous API calls for email sending are causing timeouts at >100 req/s"),
            TemplateField("options", "What options did you consider? (one per line)",
                          "e.g. \n1. Redis Queue (BullMQ)\n2. AWS SQS\n3. PostgreSQL-backed queue (pg-boss)",
                          hint="List 2–4 realistic options"),
            TemplateField("decision", "What did you decide?",
                          "e.g. Redis Queue (BullMQ) with a 3-retry policy"),
            TemplateField("rationale", "Why this option over the others?",
                          "e.g. Already have Redis in infra, BullMQ has best DX for our Node stack, lower ops overhead than SQS"),
            TemplateField("consequences", "What are the trade-offs? What becomes harder?",
                          "e.g. Must ensure Redis is HA. Adds operational complexity. Jobs lost if Redis crashes without persistence."),
        ],
        "assembler": _adr_assemble,
    },
    "api_design": {
        "description": "API endpoint design — spec before you code",
        "skill": "feature-dev:feature-dev",
        "fields": [
            TemplateField("endpoint_name", "What is this endpoint called?",
                          "e.g. Create User Invite"),
            TemplateField("purpose", "What does this endpoint do? Who calls it and why?",
                          "e.g. Admin sends invite to a new user's email. Called from admin dashboard."),
            TemplateField("method_path", "HTTP method and path?",
                          "e.g. POST /api/v1/orgs/{org_id}/invites"),
            TemplateField("auth", "How is it authenticated/authorized?",
                          "e.g. Bearer JWT, requires admin role"),
            TemplateField("request_format", "Request body / query params? (JSON schema or description)",
                          'e.g. { "email": "string (required)", "role": "admin|member (required)" }'),
            TemplateField("response_format", "Success response format?",
                          'e.g. 201 Created: { "invite_id": "uuid", "expires_at": "ISO8601" }'),
            TemplateField("error_cases", "What errors need to be handled?",
                          "e.g. 409 if email already invited, 403 if caller not admin, 422 if email invalid",
                          required=False),
        ],
        "assembler": _api_design_assemble,
    },
    "task_breakdown": {
        "description": "Break a goal into concrete ordered tasks",
        "skill": "feature-dev:feature-dev",
        "fields": [
            TemplateField("goal", "What are you trying to achieve? State the end goal.",
                          "e.g. Build a Slack notification system for deployment events"),
            TemplateField("current_state", "What exists today? What's already built?",
                          "e.g. We have a CI/CD pipeline in GitHub Actions, no Slack integration yet"),
            TemplateField("tech_stack", "What tech stack / tools are you working with?",
                          "e.g. Node.js, TypeScript, GitHub Actions, Slack Bolt SDK"),
            TemplateField("constraints", "Any constraints, deadlines, or team limits?",
                          "e.g. Solo dev, needs to ship by Friday, no new cloud services",
                          required=False),
            TemplateField("done_criteria", "What does 'done' look like?",
                          "e.g. Slack messages sent on deploy success/failure with PR link and deployer name"),
        ],
        "assembler": _task_breakdown_assemble,
    },
}


# ── Session store ──────────────────────────────────────────────────────────────


_sessions: dict[str, BuilderSession] = {}
_sessions_lock = threading.Lock()
_SESSION_TTL_SECONDS = 1800  # 30 minutes


def _purge_stale() -> None:
    """Remove sessions older than TTL."""
    now = datetime.now(timezone.utc)
    stale = [
        sid for sid, s in _sessions.items()
        if (now - s.created_at).total_seconds() > _SESSION_TTL_SECONDS
    ]
    for sid in stale:
        _sessions.pop(sid, None)


# ── Public API ─────────────────────────────────────────────────────────────────


def list_templates() -> list[dict[str, Any]]:
    """Return available templates with name, description, field count, and skill."""
    return [
        {
            "name": name,
            "description": t["description"],
            "fields": len(t["fields"]),
            "required_fields": sum(1 for f in t["fields"] if f.required),
            "skill": t.get("skill", TEMPLATE_SKILL_MAP.get(name, "feature-dev:feature-dev")),
        }
        for name, t in _TEMPLATES.items()
    ]


def start_session(template_name: str, profile: str = "default") -> dict[str, Any]:
    """Begin a new prompt-building session. Returns the first question."""
    if template_name not in _TEMPLATES:
        available = ", ".join(_TEMPLATES.keys())
        return {"error": f"Unknown template '{template_name}'. Available: {available}"}

    tpl = _TEMPLATES[template_name]
    fields: list[TemplateField] = tpl["fields"]
    session_id = uuid.uuid4().hex[:12]
    session = BuilderSession(
        session_id=session_id,
        template_name=template_name,
        answers={},
        current_field_index=0,
        profile=profile,
    )

    with _sessions_lock:
        _purge_stale()
        _sessions[session_id] = session

    first_field = fields[0]
    return {
        "session_id": session_id,
        "template": template_name,
        "description": tpl["description"],
        "total_fields": len(fields),
        "required_fields": sum(1 for f in fields if f.required),
        "progress": f"1/{len(fields)}",
        "field": first_field.name,
        "question": first_field.question,
        "placeholder": first_field.placeholder,
        "required": first_field.required,
        "hint": first_field.hint or None,
        "example": first_field.example or None,
        "status": "in_progress",
    }


def answer_field(session_id: str, answer: str) -> dict[str, Any]:
    """Record an answer and return the next question, or the assembled prompt if done."""
    with _sessions_lock:
        session = _sessions.get(session_id)

    if not session:
        return {"error": f"Session '{session_id}' not found. It may have expired. Start a new one."}

    tpl = _TEMPLATES[session.template_name]
    fields: list[TemplateField] = tpl["fields"]
    current_field = fields[session.current_field_index]

    # Validate required fields aren't left blank
    stripped = answer.strip()
    if current_field.required and not stripped:
        return {
            "session_id": session_id,
            "error": f"'{current_field.name}' is required. Please provide an answer.",
            "field": current_field.name,
            "question": current_field.question,
            "placeholder": current_field.placeholder,
            "hint": current_field.hint or None,
            "status": "needs_answer",
        }

    # Store the answer (even blank optional ones)
    session.answers[current_field.name] = stripped
    session.current_field_index += 1

    # Check if done
    if session.current_field_index >= len(fields):
        prompt = tpl["assembler"](session.answers)
        skill = tpl.get("skill", TEMPLATE_SKILL_MAP.get(session.template_name, "feature-dev:feature-dev"))
        with _sessions_lock:
            _sessions.pop(session_id, None)
        return {
            "session_id": session_id,
            "status": "complete",
            "template": session.template_name,
            "prompt": prompt,
            "field_count": len(session.answers),
            "skill_to_invoke": skill,
        }

    # Return next question
    next_field = fields[session.current_field_index]
    return {
        "session_id": session_id,
        "progress": f"{session.current_field_index + 1}/{len(fields)}",
        "answered": current_field.name,
        "field": next_field.name,
        "question": next_field.question,
        "placeholder": next_field.placeholder,
        "required": next_field.required,
        "hint": next_field.hint or None,
        "example": next_field.example or None,
        "status": "in_progress",
        "fields_remaining": len(fields) - session.current_field_index,
    }


def skip_field(session_id: str) -> dict[str, Any]:
    """Skip the current optional field and move to the next."""
    with _sessions_lock:
        session = _sessions.get(session_id)

    if not session:
        return {"error": f"Session '{session_id}' not found."}

    tpl = _TEMPLATES[session.template_name]
    fields: list[TemplateField] = tpl["fields"]
    current_field = fields[session.current_field_index]

    if current_field.required:
        return {
            "error": f"Cannot skip '{current_field.name}' — it is required.",
            "field": current_field.name,
            "question": current_field.question,
        }

    # Skip = empty answer
    return answer_field(session_id, "")


def get_session_status(session_id: str) -> dict[str, Any]:
    """Return current session state with all answers so far."""
    with _sessions_lock:
        session = _sessions.get(session_id)

    if not session:
        return {"error": f"Session '{session_id}' not found or expired."}

    tpl = _TEMPLATES[session.template_name]
    fields: list[TemplateField] = tpl["fields"]
    current_field = fields[session.current_field_index]

    return {
        "session_id": session_id,
        "template": session.template_name,
        "progress": f"{session.current_field_index + 1}/{len(fields)}",
        "current_field": current_field.name,
        "current_question": current_field.question,
        "answers_so_far": session.answers,
        "fields_remaining": len(fields) - session.current_field_index,
        "status": "in_progress",
    }


def abandon_session(session_id: str) -> dict[str, Any]:
    """Cancel and remove a session."""
    with _sessions_lock:
        removed = _sessions.pop(session_id, None)

    if removed:
        return {"status": "abandoned", "session_id": session_id}
    return {"error": f"Session '{session_id}' not found."}


def assess_prompt_quality(task: str) -> dict[str, Any]:
    """Quick heuristic quality check on a raw task string.

    Returns a score 0–1 and a suggestion if the prompt is too vague.
    Used by evaluate() to attach prompt_suggestion to low-quality decisions.
    """
    if not task:
        return {"score": 0.0, "vague": True, "reason": "Empty prompt"}

    length = len(task.strip())
    score = 1.0

    issues = []

    # Length check
    if length < 20:
        score -= 0.5
        issues.append("too short (< 20 chars)")
    elif length < 50:
        score -= 0.2
        issues.append("may be too brief")

    # No verb (very rough heuristic — just check for common action words)
    action_words = {
        "add", "build", "create", "fix", "update", "refactor", "review",
        "analyze", "implement", "design", "debug", "test", "write", "check",
        "deploy", "optimize", "migrate", "delete", "remove", "investigate",
    }
    lower = task.lower()
    has_action = any(w in lower for w in action_words)
    if not has_action and length < 80:
        score -= 0.15
        issues.append("no clear action verb")

    # No question mark or period — might be a fragment
    if length < 40 and not any(c in task for c in ("?", ".", ":", "\n")):
        score -= 0.1
        issues.append("may be a sentence fragment")

    score = max(0.0, min(1.0, score))

    result: dict[str, Any] = {
        "score": round(score, 2),
        "vague": score < 0.5,
        "length": length,
    }

    if issues:
        result["issues"] = issues

    if score < 0.5:
        # Suggest the most relevant template
        template_hint = _infer_best_template(lower)
        result["suggestion"] = (
            f"Prompt may be too vague ({', '.join(issues)}). "
            f"Try: sentigent_prompt_build(action='start', template='{template_hint}') "
            f"to build a structured prompt."
        )
        result["suggested_template"] = template_hint

    return result


def _infer_best_template(task_lower: str) -> str:
    """Heuristically pick the most relevant template for a vague task."""
    if any(w in task_lower for w in ("spec", "product", "feature", "requirement", "prd")):
        return "product_spec"
    if any(w in task_lower for w in ("pr", "pull request", "review", "merge", "diff")):
        return "pr_review"
    if any(w in task_lower for w in ("bug", "error", "crash", "broken", "fail")):
        return "bug_report"
    if any(w in task_lower for w in ("refactor", "clean", "restructure", "improve code")):
        return "code_refactor"
    if any(w in task_lower for w in ("api", "endpoint", "route", "rest", "http")):
        return "api_design"
    if any(w in task_lower for w in ("task", "breakdown", "plan", "sprint", "todo")):
        return "task_breakdown"
    if any(w in task_lower for w in ("architecture", "decision", "adr", "choose", "database")):
        return "architecture_decision"
    return "product_spec"  # sensible default
