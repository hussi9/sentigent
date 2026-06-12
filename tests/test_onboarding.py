"""Tests for the onboarding module (init, doctor, reset)."""

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sentigent.onboarding import (
    CLAUDE_MD_SECTION,
    SENTIGENT_MARKER,
    cmd_doctor,
    cmd_init,
    cmd_reset,
    _find_hook_script,
    _load_settings,
    _save_settings,
)


@pytest.fixture
def isolated_env(tmp_path: Path):
    """Create an isolated environment with fake Claude Code paths."""
    settings_path = tmp_path / ".claude" / "settings.json"
    claude_md_path = tmp_path / ".claude" / "CLAUDE.md"
    sentigent_dir = tmp_path / ".sentigent"

    # Ensure parent dirs exist
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    sentigent_dir.mkdir(parents=True, exist_ok=True)

    # Create a minimal hook script to find
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_script = hook_dir / "sentigent_hook.py"
    hook_script.write_text("# fake hook\n")

    patches = {
        "CLAUDE_SETTINGS_PATH": settings_path,
        "CLAUDE_MD_PATH": claude_md_path,
        "SENTIGENT_DIR": sentigent_dir,
    }

    with patch.multiple("sentigent.onboarding", **patches):
        yield {
            "settings_path": settings_path,
            "claude_md_path": claude_md_path,
            "sentigent_dir": sentigent_dir,
            "hook_script": str(hook_script),
            "tmp_path": tmp_path,
        }


class TestLoadSaveSettings:

    def test_load_nonexistent(self, isolated_env):
        """Loading from a nonexistent path returns empty dict."""
        result = _load_settings()
        assert result == {}

    def test_save_and_load(self, isolated_env):
        """Settings round-trip through save and load."""
        data = {"mcpServers": {"test": {"command": "echo"}}, "hooks": {}}
        _save_settings(data)

        loaded = _load_settings()
        assert loaded["mcpServers"]["test"]["command"] == "echo"

    def test_save_creates_parent_dirs(self, isolated_env):
        """Save creates parent directories if they don't exist."""
        settings_path = isolated_env["settings_path"]
        # Remove the parent dir
        if settings_path.parent.exists():
            shutil.rmtree(settings_path.parent)
        assert not settings_path.parent.exists()

        _save_settings({"test": True})
        assert settings_path.exists()

        loaded = _load_settings()
        assert loaded["test"] is True


class TestFindHookScript:

    def test_finds_dev_path(self):
        """Should find hook script relative to package in dev install."""
        # This just verifies it returns a string path
        result = _find_hook_script()
        assert isinstance(result, str)
        assert "sentigent_hook.py" in result


class TestCmdInit:

    def test_init_creates_settings(self, isolated_env):
        """init creates settings.json when it doesn't exist."""
        settings_path = isolated_env["settings_path"]
        assert not settings_path.exists()

        with patch("builtins.input", side_effect=["test_org", "default", "test_agent", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "sentigent" in settings["mcpServers"]

    def test_init_adds_mcp_server(self, isolated_env):
        """init adds sentigent MCP server entry."""
        # Create empty settings
        _save_settings({"mcpServers": {}, "hooks": {}})

        with patch("builtins.input", side_effect=["my_org", "code_review", "my_agent", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

        settings = _load_settings()
        assert "sentigent" in settings["mcpServers"]
        mcp = settings["mcpServers"]["sentigent"]
        assert "python" in os.path.basename(mcp["command"])  # Could be python, python3, python3.11, etc.
        assert mcp["args"] == ["-m", "sentigent.mcp_server"]
        assert mcp["env"]["SENTIGENT_PROFILE"] == "code_review"
        assert mcp["env"]["SENTIGENT_AGENT_ID"] == "my_agent"
        assert mcp["env"]["SENTIGENT_ORG_ID"] == "my_org"

    def test_init_adds_hooks(self, isolated_env):
        """init adds PreToolUse and PostToolUse hooks."""
        _save_settings({"mcpServers": {}, "hooks": {}})

        with patch("builtins.input", side_effect=["org", "default", "agent", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

        settings = _load_settings()
        pre_hooks = settings["hooks"]["PreToolUse"]
        post_hooks = settings["hooks"]["PostToolUse"]

        assert len(pre_hooks) >= 1
        assert len(post_hooks) >= 1

        # Verify hook has correct matcher
        pre_entry = pre_hooks[-1]
        assert pre_entry["matcher"] == "Bash|Write|Edit"
        assert "sentigent_hook.py" in pre_entry["hooks"][0]["command"]
        assert "pre" in pre_entry["hooks"][0]["command"]

        post_entry = post_hooks[-1]
        assert post_entry["matcher"] == "Bash|Write|Edit"
        assert "sentigent_hook.py" in post_entry["hooks"][0]["command"]
        assert "post" in post_entry["hooks"][0]["command"]

    def test_init_creates_claude_md(self, isolated_env):
        """init creates CLAUDE.md with Sentigent instructions."""
        with patch("builtins.input", side_effect=["org", "default", "agent", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

        claude_md = isolated_env["claude_md_path"]
        assert claude_md.exists()
        content = claude_md.read_text()
        assert SENTIGENT_MARKER in content
        assert "sentigent_evaluate" in content

    def test_init_appends_to_existing_claude_md(self, isolated_env):
        """init appends to existing CLAUDE.md without overwriting."""
        claude_md = isolated_env["claude_md_path"]
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text("# My Existing Instructions\n\nKeep this content.\n")

        with patch("builtins.input", side_effect=["org", "default", "agent", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

        content = claude_md.read_text()
        assert "My Existing Instructions" in content
        assert "Keep this content." in content
        assert SENTIGENT_MARKER in content

    def test_init_idempotent(self, isolated_env):
        """Running init twice doesn't duplicate hooks or CLAUDE.md sections."""
        _save_settings({"mcpServers": {}, "hooks": {}})

        for _ in range(2):
            with patch("builtins.input", side_effect=["org", "default", "agent", "n", "n"]):
                with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                    cmd_init()

        settings = _load_settings()
        # Should only have 1 PreToolUse and 1 PostToolUse sentigent hook
        pre_sentigent = [
            e for e in settings["hooks"].get("PreToolUse", [])
            if "sentigent_hook.py" in str(e)
        ]
        post_sentigent = [
            e for e in settings["hooks"].get("PostToolUse", [])
            if "sentigent_hook.py" in str(e)
        ]
        assert len(pre_sentigent) == 1
        assert len(post_sentigent) == 1

        # CLAUDE.md should only have the marker once
        content = isolated_env["claude_md_path"].read_text()
        assert content.count(SENTIGENT_MARKER) == 1

    def test_init_creates_database(self, isolated_env):
        """init creates the SQLite database."""
        with patch("builtins.input", side_effect=["org", "default", "test_agent_db", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

        # Check that a .db file was created in sentigent_dir
        db_files = list(isolated_env["sentigent_dir"].glob("memory_*.db"))
        assert len(db_files) >= 1


class TestCmdReset:

    def _do_init(self, isolated_env):
        """Helper to run init first."""
        _save_settings({"mcpServers": {}, "hooks": {}})
        with patch("builtins.input", side_effect=["org", "default", "agent", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

    def test_reset_removes_mcp_server(self, isolated_env):
        """reset removes sentigent from mcpServers."""
        self._do_init(isolated_env)

        settings = _load_settings()
        assert "sentigent" in settings["mcpServers"]

        cmd_reset()

        settings = _load_settings()
        assert "sentigent" not in settings["mcpServers"]

    def test_reset_removes_hooks(self, isolated_env):
        """reset removes sentigent hooks from Pre/PostToolUse."""
        self._do_init(isolated_env)
        cmd_reset()

        settings = _load_settings()
        for hook_type in ("PreToolUse", "PostToolUse"):
            hooks = settings.get("hooks", {}).get(hook_type, [])
            for entry in hooks:
                assert "sentigent_hook.py" not in str(entry)

    def test_reset_removes_claude_md_section(self, isolated_env):
        """reset removes Sentigent section from CLAUDE.md."""
        self._do_init(isolated_env)

        claude_md = isolated_env["claude_md_path"]
        assert SENTIGENT_MARKER in claude_md.read_text()

        cmd_reset()

        content = claude_md.read_text()
        assert SENTIGENT_MARKER not in content

    def test_reset_preserves_other_claude_md_content(self, isolated_env):
        """reset only removes Sentigent section, keeps everything else."""
        claude_md = isolated_env["claude_md_path"]
        claude_md.parent.mkdir(parents=True, exist_ok=True)
        claude_md.write_text("# My Rules\n\nKeep this.\n")

        self._do_init(isolated_env)
        content_after_init = claude_md.read_text()
        assert "My Rules" in content_after_init
        assert SENTIGENT_MARKER in content_after_init

        cmd_reset()

        content_after_reset = claude_md.read_text()
        assert "My Rules" in content_after_reset
        assert "Keep this." in content_after_reset
        assert SENTIGENT_MARKER not in content_after_reset

    def test_reset_preserves_database(self, isolated_env):
        """reset does NOT delete the learning database."""
        self._do_init(isolated_env)

        db_files_before = list(isolated_env["sentigent_dir"].glob("memory_*.db"))

        cmd_reset()

        db_files_after = list(isolated_env["sentigent_dir"].glob("memory_*.db"))
        assert len(db_files_after) == len(db_files_before)

    def test_reset_preserves_other_hooks(self, isolated_env):
        """reset only removes sentigent hooks, keeps others."""
        # Set up settings with a custom hook already present
        _save_settings({
            "mcpServers": {},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Write",
                        "hooks": [{"type": "command", "command": "echo 'my custom hook'"}],
                    }
                ],
            },
        })

        # Run init — it should ADD sentigent hook alongside the custom one
        with patch("builtins.input", side_effect=["org", "default", "agent", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

        settings = _load_settings()
        pre_hooks = settings["hooks"]["PreToolUse"]
        assert len(pre_hooks) == 2  # custom + sentigent

        # Now reset — should only remove sentigent, keep custom
        cmd_reset()

        settings = _load_settings()
        pre_hooks = settings["hooks"]["PreToolUse"]
        assert len(pre_hooks) == 1
        assert "my custom hook" in pre_hooks[0]["hooks"][0]["command"]

    def test_reset_idempotent(self, isolated_env):
        """Running reset twice doesn't crash."""
        self._do_init(isolated_env)
        cmd_reset()
        cmd_reset()  # Should not raise

    def test_reset_without_settings(self, isolated_env):
        """reset on a system without settings.json doesn't crash."""
        cmd_reset()  # Should not raise


class TestCmdDoctor:

    def test_doctor_runs_without_crash(self, isolated_env):
        """doctor should run without exceptions even on empty system."""
        # Just verify it doesn't raise
        cmd_doctor()

    def test_doctor_after_init(self, isolated_env):
        """doctor after init should detect all components."""
        _save_settings({"mcpServers": {}, "hooks": {}})
        with patch("builtins.input", side_effect=["org", "default", "agent", "n", "n"]):
            with patch("sentigent.onboarding._find_hook_script", return_value=isolated_env["hook_script"]):
                cmd_init()

        # Should run without errors (we can't easily capture stdout in
        # the current pattern, but no exception = pass)
        cmd_doctor()
