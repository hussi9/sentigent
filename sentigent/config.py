"""Configuration management for Sentigent.

Loads settings from (in priority order):
1. Environment variables (SENTIGENT_*)
2. Config file (~/.sentigent/config.toml or ./sentigent.toml)
3. Default values

Usage:
    from sentigent.config import get_config
    config = get_config()
    print(config.profile)
    print(config.agent_id)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SentigentConfig:
    """Runtime configuration for Sentigent."""

    profile: str = "default"
    agent_id: str = "default_agent"
    org_id: str = "default_org"
    db_path: str | None = None

    # Layer 2+3 server settings
    server_url: str | None = None
    api_key: str | None = None

    # Performance settings
    evaluate_timeout_ms: int = 50
    memory_timeout_ms: int = 30
    max_episodes_in_memory: int = 10000
    baseline_recompute_interval: int = 50  # every N outcomes
    pattern_mine_interval: int = 100  # every N outcomes

    # Episode management
    episode_ttl_days: int = 90
    max_similar_episodes: int = 10

    # Sync settings (Layer 2)
    sync_enabled: bool = False
    sync_interval_seconds: int = 300  # 5 minutes
    sync_batch_size: int = 100

    # Observability
    log_level: str = "WARNING"
    metrics_enabled: bool = True

    # Event / Webhook settings
    # Maps event types to lists of webhook URLs
    # Example: {"escalation": ["https://hooks.slack.com/..."], "circuit_breaker": [...]}
    webhooks: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> SentigentConfig:
        """Load configuration from environment variables."""
        return cls(
            profile=os.environ.get("SENTIGENT_PROFILE", "default"),
            agent_id=os.environ.get("SENTIGENT_AGENT_ID", "default_agent"),
            org_id=os.environ.get("SENTIGENT_ORG_ID", "default_org"),
            db_path=os.environ.get("SENTIGENT_DB_PATH"),
            server_url=os.environ.get("SENTIGENT_SERVER_URL"),
            api_key=os.environ.get("SENTIGENT_API_KEY"),
            evaluate_timeout_ms=int(os.environ.get("SENTIGENT_EVALUATE_TIMEOUT_MS", "50")),
            log_level=os.environ.get("SENTIGENT_LOG_LEVEL", "WARNING"),
            sync_enabled=os.environ.get("SENTIGENT_SYNC_ENABLED", "false").lower() == "true",
        )

    @classmethod
    def from_toml(cls, path: str | Path | None = None) -> SentigentConfig:
        """Load configuration from a TOML file."""
        if path is None:
            # Search order: ./sentigent.toml, ~/.sentigent/config.toml
            candidates = [
                Path("sentigent.toml"),
                Path.home() / ".sentigent" / "config.toml",
            ]
            for candidate in candidates:
                if candidate.exists():
                    path = candidate
                    break

        if path is None or not Path(path).exists():
            return cls.from_env()

        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # Python 3.10 fallback
            except ImportError:
                return cls.from_env()

        with open(path, "rb") as f:
            data = tomllib.load(f)

        sentigent_data = data.get("sentigent", data)

        config = cls.from_env()  # Start with env vars

        # Override with TOML values (env vars take precedence)
        for key in [
            "profile", "agent_id", "org_id", "db_path",
            "server_url", "api_key", "evaluate_timeout_ms",
            "memory_timeout_ms", "max_episodes_in_memory",
            "baseline_recompute_interval", "pattern_mine_interval",
            "episode_ttl_days", "max_similar_episodes",
            "sync_enabled", "sync_interval_seconds", "sync_batch_size",
            "log_level", "metrics_enabled",
        ]:
            env_key = f"SENTIGENT_{key.upper()}"
            if env_key not in os.environ and key in sentigent_data:
                setattr(config, key, sentigent_data[key])

        # Load webhook configuration from [sentigent.webhooks] section
        webhooks_data = sentigent_data.get("webhooks", {})
        if isinstance(webhooks_data, dict):
            config.webhooks = {
                k: (v if isinstance(v, list) else [v])
                for k, v in webhooks_data.items()
            }

        return config


_config: SentigentConfig | None = None


def get_config() -> SentigentConfig:
    """Get the global Sentigent configuration (lazy loaded)."""
    global _config
    if _config is None:
        _config = SentigentConfig.from_toml()
    return _config


def set_config(config: SentigentConfig | None) -> None:
    """Override the global configuration (for testing). Pass None to reset."""
    global _config
    _config = config
