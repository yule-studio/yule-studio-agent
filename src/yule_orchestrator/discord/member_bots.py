from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence, Tuple

from ..core.context_loader import ContextError, load_agent_context


GATEWAY_ROLE_KEY = "gateway"


@dataclass(frozen=True)
class MemberBotProfile:
    """One executable Discord persona inside a department.

    role is either an actual member id (``backend-engineer``) or the special
    sentinel ``gateway`` representing the department gateway bot.
    """

    agent_id: str
    role: str
    env_key: str
    token: Optional[str]
    display_label: str

    @property
    def active(self) -> bool:
        return bool(self.token)


@dataclass(frozen=True)
class MemberBotConfig:
    """Everything `yule discord member` needs to start one or all member bots."""

    agent_id: str
    profiles: Sequence[MemberBotProfile] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)

    def role_ids(self) -> Sequence[str]:
        return tuple(profile.role for profile in self.profiles)

    def get(self, role: str) -> MemberBotProfile:
        for profile in self.profiles:
            if profile.role == role:
                return profile
        available = ", ".join(self.role_ids()) or "<none>"
        raise ValueError(
            f"role '{role}' is not registered for {self.agent_id}. "
            f"Available roles: {available}."
        )

    def active_profiles(self) -> Sequence[MemberBotProfile]:
        return tuple(profile for profile in self.profiles if profile.active)


def env_key_for(agent_id: str, role: str) -> str:
    """Return the env var name for a member bot token.

    `engineering-agent` + `backend-engineer` -> `ENGINEERING_AGENT_BOT_BACKEND_ENGINEER_TOKEN`.
    Department prefix matches `env-strategy.md` §1.
    """

    prefix = _to_env_prefix(agent_id)
    role_part = _to_env_segment(role)
    return f"{prefix}_BOT_{role_part}_TOKEN"


def load_member_bot_config(repo_root: Path, agent_id: str) -> MemberBotConfig:
    """Read agent.json + env to build the member bot table.

    Missing token = inactive member. Unknown role passed via CLI is rejected
    by ``MemberBotConfig.get`` rather than here.
    """

    try:
        loaded = load_agent_context(repo_root=repo_root, agent_id=agent_id)
    except ContextError as exc:
        raise ValueError(str(exc)) from exc

    members = loaded.manifest.get("members", [])
    if not isinstance(members, list):
        raise ValueError(f"{agent_id}/agent.json members must be a list of role ids")

    warnings: list[str] = list(loaded.warnings)
    profiles: list[MemberBotProfile] = [_build_profile(agent_id, GATEWAY_ROLE_KEY)]

    for member in members:
        if not isinstance(member, str) or not member:
            warnings.append("Skipping non-string member id in manifest")
            continue
        profiles.append(_build_profile(agent_id, member))

    return MemberBotConfig(agent_id=agent_id, profiles=tuple(profiles), warnings=tuple(warnings))


def _build_profile(agent_id: str, role: str) -> MemberBotProfile:
    env_key = env_key_for(agent_id, role)
    raw = os.environ.get(env_key)
    token = raw.strip() if isinstance(raw, str) and raw.strip() else None
    return MemberBotProfile(
        agent_id=agent_id,
        role=role,
        env_key=env_key,
        token=token,
        display_label=_display_label(agent_id, role),
    )


def _display_label(agent_id: str, role: str) -> str:
    if role == GATEWAY_ROLE_KEY:
        return f"{agent_id} (gateway)"
    return f"{agent_id}/{role}"


def _to_env_prefix(agent_id: str) -> str:
    return _to_env_segment(agent_id)


def _to_env_segment(value: str) -> str:
    return value.upper().replace("-", "_").replace("/", "_")


def render_startup_summary(config: MemberBotConfig) -> Tuple[str, ...]:
    """Lines to print at launcher start so the operator can see what's active.

    Returned as a tuple so the launcher can route them through its own
    logger; tests compare against this directly.
    """

    lines: list[str] = [
        f"engineering-agent multi-bot summary for '{config.agent_id}':",
    ]
    if not config.profiles:
        lines.append("  no roles registered")
        return tuple(lines)

    for profile in config.profiles:
        status = "active" if profile.active else "skipped (token missing)"
        lines.append(f"  - {profile.display_label}: {status} [{profile.env_key}]")

    for warning in config.warnings:
        lines.append(f"  ! {warning}")

    return tuple(lines)


def select_profile_for_role(
    config: MemberBotConfig,
    role: str,
    *,
    require_token: bool = True,
) -> MemberBotProfile:
    """Resolve a CLI ``--role`` arg into a profile, with clear errors.

    Used by ``yule discord member`` so the operator gets one-shot feedback.
    """

    profile = config.get(role)
    if require_token and not profile.active:
        raise ValueError(
            f"{profile.env_key} is required to start {profile.display_label}. "
            f"Add it to .env.local before running this role bot."
        )
    return profile


def role_choices_for_help(config: MemberBotConfig) -> str:
    """Human-readable role list for CLI ``--help`` text."""

    return ", ".join(config.role_ids()) or "<none>"


def _ignore_extra_env_keys(_: Mapping[str, str]) -> None:
    """Hook reserved for later validators; intentionally a no-op for now."""
