"""Bash failure advisor — detects when Bash commands fail and suggests MCP alternatives.

When Claude Code's Bash tool fails, this advisor:
1. Classifies the failed command by operation type
2. Returns a specific MCP tool alternative
3. Tracks the failure pattern so Sentigent learns over time

The advisor surfaces its suggestions as a `message` in the PostToolUse hook
response, which Claude Code displays before the next tool call.
"""
from __future__ import annotations

import re
from typing import NamedTuple


class Alternative(NamedTuple):
    tool: str
    example: str
    reason: str


# ── Exit-code detection ───────────────────────────────────────────────────────
# Claude Code sets tool_response["interrupted"] or includes exit code in output.
# We also look for these patterns in the response text.
_EXIT_CODE_RE = re.compile(
    r"exit(?:ed with| code|:)\s*([1-9]\d*)|"
    r"returned non-zero exit status\s*([1-9]\d*)|"
    r"Process exited with code ([1-9]\d*)",
    re.IGNORECASE,
)

_TOOL_ERROR_RE = re.compile(
    r"command not found|No such file or directory|Permission denied|"
    r"ENOENT|EACCES|EPERM|cannot open|failed to|"
    r"Connection refused|Connection timed out|"
    r"SSL.*error|certificate verify failed|"
    r"syntax error|unexpected token|"
    r"ModuleNotFoundError|ImportError|"
    r"Error:|error:|FATAL|fatal:",
    re.IGNORECASE,
)


def is_bash_failure(
    response_str: str,
    resp_error: str | None,
    tool_interrupted: bool = False,
) -> bool:
    """Return True if this Bash execution genuinely failed."""
    if resp_error:
        return True
    if tool_interrupted:
        return True
    if _EXIT_CODE_RE.search(response_str):
        return True
    if _TOOL_ERROR_RE.search(response_str):
        return True
    return False


# ── Command classification → MCP alternative ─────────────────────────────────
_ALTERNATIVES: list[tuple[re.Pattern, Alternative]] = [
    # File reading
    (
        re.compile(r"\b(cat|head|tail|less|more)\s+\S+", re.IGNORECASE),
        Alternative(
            tool="Read tool",
            example='Use the Read tool with file_path="/path/to/file"',
            reason="The Read tool handles file reading reliably without shell quoting issues",
        ),
    ),
    # File search
    (
        re.compile(r"\bfind\s+\S+.*-name\b|\bls\s+-[lRa]*\s+\S+", re.IGNORECASE),
        Alternative(
            tool="Glob tool",
            example='Use the Glob tool with pattern="**/*.py"',
            reason="Glob is a dedicated file finder that avoids shell path escaping",
        ),
    ),
    # Content search
    (
        re.compile(r"\b(grep|rg|ripgrep|ag)\s+", re.IGNORECASE),
        Alternative(
            tool="Grep tool",
            example='Use the Grep tool with pattern="your search" and path="."',
            reason="Grep tool handles Unicode, large files, and binary files safely",
        ),
    ),
    # Git operations
    (
        re.compile(r"\bgit\s+(status|log|diff|show|branch|remote)\b", re.IGNORECASE),
        Alternative(
            tool="mcp__github",
            example="Use mcp__github tools for repository queries",
            reason="GitHub MCP provides structured git data without shell access",
        ),
    ),
    # Database / psql / mysql
    (
        re.compile(r"\b(psql|mysql|sqlite3)\s+", re.IGNORECASE),
        Alternative(
            tool="mcp__supabase or db-expert agent",
            example="Use mcp__supabase for Supabase queries, or spawn a db-expert Task agent",
            reason="Database MCP tools handle connection pooling and auth correctly",
        ),
    ),
    # curl / wget / HTTP
    (
        re.compile(r"\b(curl|wget|httpie|http)\s+", re.IGNORECASE),
        Alternative(
            tool="WebFetch tool",
            example='Use the WebFetch tool with url="https://..." and prompt="extract..."',
            reason="WebFetch handles redirects, auth, and content extraction",
        ),
    ),
    # Browser / playwright
    (
        re.compile(r"\b(playwright|puppeteer|chromium|chrome)\s+", re.IGNORECASE),
        Alternative(
            tool="mcp__playwright",
            example="Use mcp__playwright tools for browser automation",
            reason="Playwright MCP manages browser lifecycle without subprocess issues",
        ),
    ),
    # Docker
    (
        re.compile(r"\bdocker\s+", re.IGNORECASE),
        Alternative(
            tool="mcp__desktop-commander",
            example="Use mcp__desktop-commander to run Docker commands with proper TTY handling",
            reason="desktop-commander handles interactive commands that Bash tool cannot",
        ),
    ),
    # npm / yarn / pnpm install
    (
        re.compile(r"\b(npm|yarn|pnpm)\s+(install|i|add|ci)\b", re.IGNORECASE),
        Alternative(
            tool="mcp__desktop-commander",
            example="Use mcp__desktop-commander for package installs that need TTY or long timeouts",
            reason="Package installs can take longer than the Bash tool timeout allows",
        ),
    ),
    # Python script execution
    (
        re.compile(r"\bpython3?\s+-m\s+\S+|\bpython3?\s+\S+\.py\b", re.IGNORECASE),
        Alternative(
            tool="mcp__desktop-commander",
            example="Use mcp__desktop-commander for long-running Python scripts",
            reason="desktop-commander supports streaming output and proper stdin handling",
        ),
    ),
    # File copy / move
    (
        re.compile(r"\b(cp|mv)\s+\S+\s+\S+", re.IGNORECASE),
        Alternative(
            tool="mcp__filesystem",
            example="Use mcp__filesystem copy_file or move_file tools",
            reason="Filesystem MCP avoids path escaping bugs in shell",
        ),
    ),
    # mkdir / rm (archive pattern)
    (
        re.compile(r"\b(mkdir|rmdir)\s+", re.IGNORECASE),
        Alternative(
            tool="mcp__filesystem",
            example="Use mcp__filesystem create_directory tool",
            reason="Filesystem MCP handles nested paths and permissions cleanly",
        ),
    ),
]

_GENERIC_ALTERNATIVE = Alternative(
    tool="mcp__desktop-commander",
    example="Use mcp__desktop-commander execute_command for shell commands that need better error handling",
    reason="desktop-commander provides richer error context and interactive input support",
)


def suggest_alternative(command: str) -> Alternative | None:
    """Return an MCP alternative for a failed Bash command, or None if generic."""
    for pattern, alt in _ALTERNATIVES:
        if pattern.search(command):
            return alt
    return None


def format_advice(command: str, error_snippet: str) -> str:
    """Format a human-readable advisory message for Claude Code."""
    alt = suggest_alternative(command) or _GENERIC_ALTERNATIVE

    cmd_preview = command[:80].rstrip() + ("..." if len(command) > 80 else "")
    lines = [
        f"Sentigent detected Bash failure: `{cmd_preview}`",
        f"Error: {error_snippet[:120]}",
        f"Suggested alternative: {alt.tool}",
        f"→ {alt.example}",
        f"Why: {alt.reason}",
    ]
    return "\n".join(lines)
