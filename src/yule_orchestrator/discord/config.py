from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DiscordBotConfig:
    token: str
    application_id: int
    guild_id: int
    daily_channel_id: Optional[int] = None

    @classmethod
    def from_env(cls) -> "DiscordBotConfig":
        return cls(
            token=_required_env("DISCORD_BOT_TOKEN"),
            application_id=_required_int_env("DISCORD_APPLICATION_ID"),
            guild_id=_required_int_env("DISCORD_GUILD_ID"),
            daily_channel_id=_optional_int_env("DISCORD_DAILY_CHANNEL_ID"),
        )


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required. Add it to .env.local before running the Discord bot.")
    return value


def _required_int_env(name: str) -> int:
    value = _required_env(name)
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer value, got: {value!r}") from exc


def _optional_int_env(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer value, got: {value!r}") from exc
