"""Onboarding — automated setup for Sentigent integration with Claude Code.

Handles:
- sentigent init: Interactive setup that patches Claude Code config
- sentigent doctor: Health check verifying all components work
- sentigent reset: Clean removal of Sentigent from Claude Code config

All operations are idempotent and non-destructive.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


# ─── Constants ───────────────────────────────────────────────────────────────

CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CLAUDE_MD_PATH = Path.home() / ".claude" / "CLAUDE.md"
SENTIGENT_DIR = Path.home() / ".sentigent"

SENTIGENT_MARKER = "## Sentigent Judgment Layer (ACTIVE)"

# The hook command template — uses absolute path to the installed package
HOOK_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "claude-plugin" / "hooks" / "sentigent_hook.py"

CLAUDE_MD_SECTION = """
## Sentigent Judgment Layer (ACTIVE)

Sentigent is a self-learning judgment layer that evaluates your actions and learns from outcomes.
It runs as an MCP server + PreToolUse/PostToolUse hooks.

### ALWAYS call `sentigent_evaluate` before:
- Destructive commands (rm, DROP, reset --hard, force push)
- Deploy/publish/release operations
- Writing to sensitive files (.env, credentials, configs, keys)
- Operations touching production data or databases
- When your confidence in an action is below 0.7
- Large file changes (50+ lines)

### How to call:
```
sentigent_evaluate(
  tool_name="Bash",
  tool_input="the command or action",
  context='{"reason": "why you are doing this", "confidence": 0.8}'
)
```

### Act on the response:
- **proceed** -> go ahead
- **slow_down** -> add extra validation, double-check your approach
- **enrich** -> gather more context before acting (read more files, check docs)
- **escalate** -> STOP and ask the user before proceeding

### Record outcomes:
- After tests pass/fail: `sentigent_outcome(trace_id, "correct"/"incorrect")`
- After user says good/bad: `sentigent_feedback(trace_id, was_helpful=true/false)`
- After builds succeed/fail: `sentigent_outcome(trace_id, "correct"/"incorrect")`

### Check your learning:
- `sentigent_score()` -> see judgment accuracy and learned baselines
- `sentigent_patterns()` -> see what patterns you've learned

### Important:
- Hooks also run passively on Bash/Write/Edit as a safety net
- Even if you forget to call sentigent_evaluate, the hooks will catch destructive ops
- Be aggressive about calling evaluate -- more data = faster learning
- Always record outcomes when you know them
"""


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _print_ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def _print_fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def _print_warn(msg: str) -> None:
    print(f"  \033[33m!\033[0m {msg}")


def _prompt(label: str, default: str) -> str:
    """Prompt user for input with a default value."""
    try:
        value = input(f"  {label} [{default}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        value = ""
    return value or default


def _find_hook_script() -> str:
    """Find the absolute path to sentigent_hook.py."""
    # Check relative to this file (development install)
    dev_path = Path(__file__).resolve().parent.parent / "claude-plugin" / "hooks" / "sentigent_hook.py"
    if dev_path.exists():
        return str(dev_path)

    # Check in site-packages (pip installed)
    import sentigent
    pkg_dir = Path(sentigent.__file__).resolve().parent.parent
    pkg_path = pkg_dir / "claude-plugin" / "hooks" / "sentigent_hook.py"
    if pkg_path.exists():
        return str(pkg_path)

    # Fallback: copy to ~/.sentigent/ and use from there
    fallback = SENTIGENT_DIR / "sentigent_hook.py"
    if fallback.exists():
        return str(fallback)

    return str(dev_path)  # Best guess


def _load_settings() -> dict[str, Any]:
    """Load Claude Code settings.json."""
    if not CLAUDE_SETTINGS_PATH.exists():
        return {}
    with open(CLAUDE_SETTINGS_PATH) as f:
        return json.load(f)


def _save_settings(settings: dict[str, Any]) -> None:
    """Save Claude Code settings.json."""
    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CLAUDE_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


# ─── Init Command ────────────────────────────────────────────────────────────

def cmd_init() -> None:
    """Interactive setup for Sentigent + Claude Code."""
    print()
    print("  \033[1mSentigent — The judgment layer that learns.\033[0m")
    print()

    # Step 1: Gather config
    from sentigent.profiles.registry import list_profiles
    available_profiles = list_profiles()

    org_id = _prompt("Org name", "default_org")
    print(f"  Available profiles: {', '.join(available_profiles)}, default")
    profile = _prompt("Profile", "code_review")
    agent_id = _prompt("Agent ID", "default_agent")

    print()
    print("  Detecting environment...")

    # Step 2: Detect Claude Code. A pre-existing ~/.claude dir/settings.json or a
    # `claude` binary on PATH are both genuine signals; the absence of both means
    # this machine has no Claude Code to integrate with, so we degrade to
    # standalone mode instead of silently claiming "detected" for a directory we
    # just created ourselves.
    claude_dir_existed = CLAUDE_SETTINGS_PATH.parent.exists()
    claude_settings_existed = CLAUDE_SETTINGS_PATH.exists()
    claude_binary = shutil.which("claude")
    claude_code_present = claude_dir_existed or claude_binary is not None

    if claude_code_present:
        if not claude_settings_existed:
            _print_warn("~/.claude/settings.json not found — creating it")
            _save_settings({"mcpServers": {}, "hooks": {}})
        _print_ok("Claude Code detected" + ("" if claude_dir_existed else " (claude CLI on PATH)"))
    else:
        _print_warn("Claude Code not detected on this machine")
        print("  Running in standalone mode: the judgment database, policies, and")
        print("  CLI commands (doctor/score/practices/...) still work fully.")
        print("  MCP server + hook integration is skipped since there's no Claude")
        print("  Code install to wire into — install it and re-run `sentigent init`")
        print("  to enable in-editor hooks later.")

    print()
    print("  Configuring...")

    # Detect the Python interpreter (uses venv python if active)
    python_path = sys.executable

    if claude_code_present:
        hook_script = _find_hook_script()

        # Step 3: Patch MCP server
        settings = _load_settings()

        if "mcpServers" not in settings:
            settings["mcpServers"] = {}

        settings["mcpServers"]["sentigent"] = {
            "command": python_path,
            "args": ["-m", "sentigent.mcp_server"],
            "env": {
                "SENTIGENT_PROFILE": profile,
                "SENTIGENT_AGENT_ID": agent_id,
                "SENTIGENT_ORG_ID": org_id,
            },
        }
        _print_ok("MCP server added to settings.json")

        # Step 4: Patch hooks
        if "hooks" not in settings:
            settings["hooks"] = {}

        # PreToolUse hook
        pre_hooks = settings["hooks"].get("PreToolUse", [])
        pre_cmd = f"cat | {python_path} {hook_script} pre 2>/dev/null || echo '{{\"decision\": \"approve\"}}'"

        # Check if already present
        has_sentigent_pre = any(
            any(h.get("command", "").endswith("sentigent_hook.py pre 2>/dev/null || echo '{\"decision\": \"approve\"}'")
                for h in entry.get("hooks", []))
            for entry in pre_hooks
            if isinstance(entry, dict)
        )

        if not has_sentigent_pre:
            pre_hooks.append({
                "matcher": "Bash|Write|Edit",
                "hooks": [{"type": "command", "command": pre_cmd}],
            })
            settings["hooks"]["PreToolUse"] = pre_hooks
        _print_ok("PreToolUse hook added (safety net)")

        # PostToolUse hook
        post_hooks = settings["hooks"].get("PostToolUse", [])
        post_cmd = f"cat | {python_path} {hook_script} post 2>/dev/null || echo '{{\"decision\": \"approve\"}}'"

        has_sentigent_post = any(
            any(h.get("command", "").endswith("sentigent_hook.py post 2>/dev/null || echo '{\"decision\": \"approve\"}'")
                for h in entry.get("hooks", []))
            for entry in post_hooks
            if isinstance(entry, dict)
        )

        if not has_sentigent_post:
            post_hooks.append({
                "matcher": "Bash|Write|Edit",
                "hooks": [{"type": "command", "command": post_cmd}],
            })
            settings["hooks"]["PostToolUse"] = post_hooks
        _print_ok("PostToolUse hook added (outcome recording)")

        _save_settings(settings)

        # Step 5: Patch CLAUDE.md
        CLAUDE_MD_PATH.parent.mkdir(parents=True, exist_ok=True)

        if CLAUDE_MD_PATH.exists():
            existing = CLAUDE_MD_PATH.read_text()
            if SENTIGENT_MARKER in existing:
                _print_ok("CLAUDE.md already has Sentigent instructions (skipped)")
            else:
                with open(CLAUDE_MD_PATH, "a") as f:
                    f.write(CLAUDE_MD_SECTION)
                _print_ok("Behavioral instructions added to ~/.claude/CLAUDE.md")
        else:
            CLAUDE_MD_PATH.write_text(CLAUDE_MD_SECTION.lstrip())
            _print_ok("Created ~/.claude/CLAUDE.md with Sentigent instructions")

    # Step 6: Initialize DB
    SENTIGENT_DIR.mkdir(parents=True, exist_ok=True)
    from sentigent.memory.store import MemoryStore
    db_path = str(SENTIGENT_DIR / f"memory_{agent_id}.db")
    store = MemoryStore(agent_id=agent_id, org_id=org_id, db_path=db_path)
    _print_ok(f"Database created: {store.db_path}")

    # Step 6b: Create default policies
    from sentigent.policies import create_default_policies
    policies_path = SENTIGENT_DIR / "policies.json"
    policies = create_default_policies(policies_path)
    _print_ok(f"Policies created: {len(policies)} default rules ({policies_path})")

    # Step 7: Copy hook script to ~/.sentigent/ for reliability
    if claude_code_present:
        hook_source = Path(hook_script)
        hook_dest = SENTIGENT_DIR / "sentigent_hook.py"
        if hook_source.exists():
            if not hook_dest.exists():
                shutil.copy2(hook_source, hook_dest)
                _print_ok(f"Hook script copied to {hook_dest}")
        else:
            _print_fail(f"Hook script not found at {hook_source}")
            _print_warn(
                "PreToolUse/PostToolUse hooks were registered but point at a "
                "missing file — they will no-op until this is fixed."
            )
            _print_warn("Try reinstalling: pip install --force-reinstall sentigent")

    # Step 8: Optional Layer 2 (Supabase) setup
    print()
    print("  \033[1mLayer 2 — Org-wide learning (optional)\033[0m")
    print("  Enables cross-agent patterns and org-wide baselines in Supabase.")
    print()
    try:
        enable_l2 = input("  Enable Layer 2 Supabase sync? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        enable_l2 = "n"

    if enable_l2 == "y":
        supabase_url = _prompt("  Supabase project URL", "https://your-project.supabase.co")
        service_key = _prompt("  Supabase service_role key", "")

        if supabase_url and service_key:
            # Write to .env in the current directory
            env_path = Path(".env")
            env_lines = env_path.read_text().splitlines() if env_path.exists() else []

            # Update or append each key
            env_updates = {
                "SUPABASE_URL": supabase_url,
                "SUPABASE_SERVICE_ROLE_KEY": service_key,
                "SENTIGENT_ORG_ID": org_id,
            }
            for key, val in env_updates.items():
                found = False
                for i, line in enumerate(env_lines):
                    if line.startswith(f"{key}="):
                        env_lines[i] = f"{key}={val}"
                        found = True
                        break
                if not found:
                    env_lines.append(f"{key}={val}")

            env_path.write_text("\n".join(env_lines) + "\n")
            _print_ok(f"Supabase credentials written to {env_path.resolve()}")

            # Add Supabase env vars to MCP server config
            settings = _load_settings()
            if "sentigent" in settings.get("mcpServers", {}):
                settings["mcpServers"]["sentigent"]["env"]["SUPABASE_URL"] = supabase_url
                settings["mcpServers"]["sentigent"]["env"]["SENTIGENT_SYNC_ENABLED"] = "true"
                _save_settings(settings)
                _print_ok("MCP server updated with Supabase URL")

            # Test connection
            try:
                from supabase import create_client
                client = create_client(supabase_url, service_key)
                client.table("synced_episodes").select("id").limit(1).execute()
                _print_ok("Supabase connection verified ✓")
            except ImportError:
                _print_warn("supabase-py not installed — run: pip install supabase")
            except Exception as e:
                _print_warn(f"Connection test: {str(e)[:80]} (check URL/key)")
        else:
            _print_warn("Skipped — no credentials provided")
    else:
        _print_warn("Layer 2 skipped (can be enabled later with: sentigent init)")

    # Step 9: Optional AI Coach setup (ANTHROPIC_API_KEY)
    print()
    print("  \033[1mAI Interaction Coach (optional)\033[0m")
    print("  Requires an Anthropic API key to generate natural language suggestions.")
    print("  Without it, the coach uses rule-based fallback suggestions (still useful).")
    print()
    setup_coach = input("  Enable AI coach? [y/N]: ").strip().lower()
    if setup_coach == "y":
        import os as _os
        existing_key = _os.environ.get("ANTHROPIC_API_KEY", "")
        if existing_key:
            print(f"  ANTHROPIC_API_KEY already set in environment ({existing_key[:12]}...)")
            _print_ok("AI coach ready — run: sentigent coach")
        else:
            api_key = input("  Anthropic API key (sk-ant-...): ").strip()
            if api_key.startswith("sk-"):
                # Write to .env
                env_path = Path(".env")
                env_content = env_path.read_text() if env_path.exists() else ""
                if "ANTHROPIC_API_KEY" not in env_content:
                    with env_path.open("a") as f:
                        f.write(f"\nANTHROPIC_API_KEY={api_key}\n")
                    _print_ok(f"API key saved to {env_path}")
                else:
                    _print_warn("ANTHROPIC_API_KEY already in .env — update it manually if needed")
                _print_ok("AI coach ready — run: sentigent coach")
            else:
                _print_warn("Invalid key format — skipped. Set ANTHROPIC_API_KEY env var manually.")
    else:
        _print_warn("AI coach skipped — rule-based fallback will be used. Set ANTHROPIC_API_KEY anytime.")

    print()
    if claude_code_present:
        print("  \033[1mDone! Restart Claude Code to activate Sentigent.\033[0m")
    else:
        print("  \033[1mDone! Sentigent is set up in standalone mode.\033[0m")
        print("  Try: sentigent doctor   sentigent score   sentigent practices list")
    print()


# ─── Doctor Command ──────────────────────────────────────────────────────────

def cmd_doctor() -> None:
    """Health check — verify all Sentigent components are working."""
    print()
    print("  \033[1mSentigent Health Check\033[0m")
    print()

    # Pre-init short-circuit: ~/.sentigent is the one directory `sentigent init`
    # always creates. If it's missing, nothing has been set up yet — say so
    # plainly instead of running the full checklist and reporting a scary list
    # of "errors" for a state that just means "you haven't run init yet".
    if not SENTIGENT_DIR.exists():
        _print_warn("Sentigent has not been initialized yet.")
        print()
        print("  Run `sentigent init` first, then re-run `sentigent doctor`.")
        print()
        return

    warnings = 0
    errors = 0

    # Claude Code is optional — Sentigent works standalone (DB, CLI, policies)
    # without it. Only treat Claude Code integration as "expected" when there's
    # actual evidence Claude Code is present on this machine.
    claude_code_present = CLAUDE_SETTINGS_PATH.parent.exists() or shutil.which("claude") is not None

    # 1. Package installed
    try:
        from sentigent import __version__
        _print_ok(f"Package installed: sentigent {__version__}")
    except ImportError:
        _print_fail("Package not installed")
        errors += 1

    # 2. MCP dependency (only relevant when integrating with Claude Code)
    try:
        import mcp  # noqa: F401
        _print_ok("MCP dependency: installed")
    except ImportError:
        if claude_code_present:
            _print_fail("MCP dependency: NOT installed (pip install sentigent[mcp])")
            errors += 1
        else:
            _print_warn("MCP dependency: not installed (only needed for Claude Code integration)")
            warnings += 1

    # 3. Config
    from sentigent.config import get_config
    config = get_config()
    _print_ok(f"Config: profile={config.profile}, agent={config.agent_id}, org={config.org_id}")

    # 4. Database
    db_path = config.db_path or str(SENTIGENT_DIR / f"memory_{config.agent_id}.db")
    if Path(db_path).exists():
        from sentigent.memory.store import MemoryStore
        store = MemoryStore(agent_id=config.agent_id, org_id=config.org_id, db_path=db_path)
        episode_count = store.get_episode_count()
        _print_ok(f"Database: {db_path} ({episode_count} episodes)")

        # Judgment score
        total, correct = store.get_outcome_counts()
        if total > 0:
            score = correct / total
            _print_ok(f"Judgment score: {score:.0%} ({correct}/{total} correct)")
        else:
            _print_warn("Judgment score: no outcomes yet (need ~50 decisions with feedback)")
            warnings += 1

        # Baselines
        baselines = store.get_baselines()
        if baselines:
            _print_ok(f"Learned baselines: {len(baselines)} metrics")
        else:
            _print_warn("Learned baselines: none yet (need ~50 outcomes to start learning)")
            warnings += 1
    else:
        _print_warn(f"Database: not created yet (run sentigent init)")
        warnings += 1

    # 5. Claude Code MCP
    if CLAUDE_SETTINGS_PATH.exists():
        settings = _load_settings()
        mcp_servers = settings.get("mcpServers", {})
        if "sentigent" in mcp_servers:
            _print_ok("Claude Code MCP: sentigent registered")
        else:
            _print_fail("Claude Code MCP: sentigent NOT registered (run sentigent init)")
            errors += 1

        # 6. Hooks
        hooks = settings.get("hooks", {})
        pre_hooks = hooks.get("PreToolUse", [])
        post_hooks = hooks.get("PostToolUse", [])

        has_pre = any(
            "sentigent_hook.py" in str(entry)
            for entry in pre_hooks
        )
        has_post = any(
            "sentigent_hook.py" in str(entry)
            for entry in post_hooks
        )

        if has_pre and has_post:
            _print_ok("Claude Code hooks: PreToolUse + PostToolUse active")
        elif has_pre:
            _print_warn("Claude Code hooks: only PreToolUse (missing PostToolUse)")
            warnings += 1
        elif has_post:
            _print_warn("Claude Code hooks: only PostToolUse (missing PreToolUse)")
            warnings += 1
        else:
            _print_fail("Claude Code hooks: NOT configured (run sentigent init)")
            errors += 1
    elif claude_code_present:
        _print_warn("Claude Code CLI found, but not yet configured (run sentigent init)")
        warnings += 1
    else:
        _print_ok("Standalone mode: no Claude Code detected — MCP server + hooks skipped")

    # 7. CLAUDE.md
    if CLAUDE_MD_PATH.exists():
        content = CLAUDE_MD_PATH.read_text()
        if SENTIGENT_MARKER in content:
            _print_ok("CLAUDE.md: Sentigent instructions present")
        else:
            _print_warn("CLAUDE.md: exists but missing Sentigent instructions (run sentigent init)")
            warnings += 1
    elif claude_code_present:
        _print_warn("CLAUDE.md: not found (run sentigent init)")
        warnings += 1
    else:
        _print_ok("CLAUDE.md: not applicable in standalone mode")

    # 8. Hook script accessible (only relevant for Claude Code integration)
    hook_script = _find_hook_script()
    if Path(hook_script).exists():
        _print_ok(f"Hook script: {hook_script}")
    elif claude_code_present:
        _print_fail(f"Hook script: NOT found at {hook_script}")
        errors += 1
    else:
        _print_ok("Hook script: not applicable in standalone mode")

    # 9. Policies
    policies_path = SENTIGENT_DIR / "policies.json"
    if policies_path.exists():
        from sentigent.policies import load_policies
        policies = load_policies(policies_path)
        active = [p for p in policies if p.enabled]
        _print_ok(f"Policies: {len(active)} active rules ({policies_path})")
    else:
        _print_warn("Policies: not found (run sentigent init to create defaults)")
        warnings += 1

    # Summary
    print()
    if errors == 0 and warnings == 0:
        print("  \033[32mOverall: HEALTHY\033[0m")
    elif errors == 0:
        print(f"  \033[33mOverall: HEALTHY ({warnings} warning{'s' if warnings > 1 else ''} — normal for new install)\033[0m")
    else:
        print(f"  \033[31mOverall: UNHEALTHY ({errors} error{'s' if errors > 1 else ''}, {warnings} warning{'s' if warnings > 1 else ''})\033[0m")
        print("  Run: sentigent init")
    print()


# ─── Reset Command ───────────────────────────────────────────────────────────

def cmd_reset() -> None:
    """Remove Sentigent from Claude Code config (keeps learning DB)."""
    print()
    print("  \033[1mSentigent Reset\033[0m")
    print()

    if not CLAUDE_SETTINGS_PATH.exists():
        _print_warn("No Claude Code settings found — nothing to reset")
        print()
        return

    settings = _load_settings()
    changed = False

    # Remove MCP server
    mcp_servers = settings.get("mcpServers", {})
    if "sentigent" in mcp_servers:
        del mcp_servers["sentigent"]
        _print_ok("Removed sentigent MCP server")
        changed = True
    else:
        _print_warn("MCP server not found (already removed)")

    # Remove hooks
    for hook_type in ("PreToolUse", "PostToolUse"):
        hooks = settings.get("hooks", {}).get(hook_type, [])
        original_len = len(hooks)
        hooks = [
            entry for entry in hooks
            if "sentigent_hook.py" not in str(entry)
        ]
        if len(hooks) < original_len:
            if "hooks" not in settings:
                settings["hooks"] = {}
            settings["hooks"][hook_type] = hooks
            _print_ok(f"Removed {hook_type} sentigent hook")
            changed = True

    if changed:
        _save_settings(settings)

    # Remove CLAUDE.md section
    if CLAUDE_MD_PATH.exists():
        content = CLAUDE_MD_PATH.read_text()
        if SENTIGENT_MARKER in content:
            # Remove from marker to next ## heading or end of file
            lines = content.split("\n")
            new_lines = []
            skipping = False
            for line in lines:
                if line.strip() == SENTIGENT_MARKER.strip():
                    skipping = True
                    continue
                if skipping and line.startswith("## ") and SENTIGENT_MARKER.strip() not in line:
                    skipping = False
                if not skipping:
                    new_lines.append(line)
            CLAUDE_MD_PATH.write_text("\n".join(new_lines))
            _print_ok("Removed Sentigent section from CLAUDE.md")
        else:
            _print_warn("CLAUDE.md has no Sentigent section (already removed)")

    print()
    print("  Learning database preserved at ~/.sentigent/")
    print("  To re-enable: sentigent init")
    print()
