"""Tests for the CLI entry point and command routing."""

import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from sentigent.cli import main


class TestCLIHelp:

    def test_help_shows_all_commands(self):
        """--help should list all available subcommands."""
        with pytest.raises(SystemExit) as exc_info:
            sys.argv = ["sentigent", "--help"]
            main()
        assert exc_info.value.code == 0

    def test_version_flag(self):
        """--version should print version and exit."""
        with pytest.raises(SystemExit) as exc_info:
            sys.argv = ["sentigent", "--version"]
            main()
        assert exc_info.value.code == 0


class TestCLIRouting:

    def test_init_routes_to_onboarding(self):
        """'sentigent init' should call cmd_init."""
        with patch("sentigent.onboarding.cmd_init") as mock_init:
            sys.argv = ["sentigent", "init"]
            main()
            mock_init.assert_called_once()

    def test_doctor_routes_to_onboarding(self):
        """'sentigent doctor' should call cmd_doctor."""
        with patch("sentigent.onboarding.cmd_doctor") as mock_doctor:
            sys.argv = ["sentigent", "doctor"]
            main()
            mock_doctor.assert_called_once()

    def test_reset_routes_to_onboarding(self):
        """'sentigent reset' should call cmd_reset."""
        with patch("sentigent.onboarding.cmd_reset") as mock_reset:
            sys.argv = ["sentigent", "reset"]
            main()
            mock_reset.assert_called_once()

    def test_dashboard_routes_to_dashboard(self):
        """'sentigent dashboard' should call cmd_dashboard."""
        with patch("sentigent.dashboard.cmd_dashboard") as mock_dash:
            sys.argv = ["sentigent", "dashboard"]
            main()
            mock_dash.assert_called_once()

    def test_web_routes_to_dashboard_web(self):
        """'sentigent web' should call cmd_web with default port."""
        with patch("sentigent.dashboard.cmd_web") as mock_web:
            sys.argv = ["sentigent", "web"]
            main()
            mock_web.assert_called_once_with(port=7777)

    def test_web_custom_port(self):
        """'sentigent web --port 9999' should pass custom port."""
        with patch("sentigent.dashboard.cmd_web") as mock_web:
            sys.argv = ["sentigent", "web", "--port", "9999"]
            main()
            mock_web.assert_called_once_with(port=9999)

    def test_profiles_command(self):
        """'sentigent profiles' should not crash."""
        sys.argv = ["sentigent", "profiles"]
        # Should not raise
        main()

    def test_no_command_shows_help(self, capsys):
        """No subcommand should show help."""
        sys.argv = ["sentigent"]
        main()
        captured = capsys.readouterr()
        assert "sentigent" in captured.out.lower() or "usage" in captured.out.lower()
