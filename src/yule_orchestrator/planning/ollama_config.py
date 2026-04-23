from __future__ import annotations

from dataclasses import dataclass
import os

DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "gemma3:latest"
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class OllamaPlanningConfig:
    enabled: bool
    endpoint: str
    model: str
    timeout_seconds: int


def load_ollama_planning_config() -> OllamaPlanningConfig:
    return OllamaPlanningConfig(
        enabled=_bool_env("OLLAMA_PLANNING_ENABLED", default=False),
        endpoint=_string_env("OLLAMA_ENDPOINT", DEFAULT_OLLAMA_ENDPOINT),
        model=_string_env("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        timeout_seconds=_positive_int_env("OLLAMA_TIMEOUT_SECONDS", DEFAULT_OLLAMA_TIMEOUT_SECONDS),
    )


def _string_env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "y", "on"}


def _positive_int_env(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer value, got: {value!r}") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than 0, got: {value!r}")
    return parsed
