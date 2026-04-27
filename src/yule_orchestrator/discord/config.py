from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from typing import Optional


@dataclass(frozen=True)
class DiscordBotConfig:
    token: str
    application_id: Optional[int]
    guild_id: int
    daily_channel_id: Optional[int] = None
    checkpoint_channel_id: Optional[int] = None
    conversation_channel_id: Optional[int] = None
    notify_user_id: Optional[int] = None
    daily_briefing_time: Optional[time] = None
    checkpoint_prefetch_minutes: int = 5

    @property
    def effective_checkpoint_channel_id(self) -> Optional[int]:
        return self.checkpoint_channel_id or self.daily_channel_id

    @classmethod
    def from_env(cls) -> "DiscordBotConfig":
        return cls(
            token=_required_env("DISCORD_BOT_TOKEN"),
            application_id=_optional_int_env("DISCORD_APPLICATION_ID"),
            guild_id=_required_int_env("DISCORD_GUILD_ID"),
            daily_channel_id=_optional_int_env("DISCORD_DAILY_CHANNEL_ID"),
            checkpoint_channel_id=_optional_int_env("DISCORD_CHECKPOINT_CHANNEL_ID"),
            conversation_channel_id=_optional_int_env("DISCORD_CONVERSATION_CHANNEL_ID"),
            notify_user_id=_optional_int_env("DISCORD_NOTIFY_USER_ID"),
            daily_briefing_time=_optional_time_env("DISCORD_DAILY_BRIEFING_TIME"),
            checkpoint_prefetch_minutes=_optional_positive_int_env(
                "DISCORD_CHECKPOINT_PREFETCH_MINUTES",
                default=5,
            ),
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


def _optional_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    value = raw.strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer value, got: {value!r}") from exc

    if parsed <= 0:
        raise ValueError(f"{name} must be greater than 0, got: {value!r}")

    return parsed


def _optional_time_env(name: str) -> Optional[time]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None

    value = raw.strip()
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"{name} must use HH:MM format, got: {value!r}")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ValueError(f"{name} must use HH:MM format, got: {value!r}") from exc

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(f"{name} must use a valid 24-hour time, got: {value!r}")

    return time(hour=hour, minute=minute)
