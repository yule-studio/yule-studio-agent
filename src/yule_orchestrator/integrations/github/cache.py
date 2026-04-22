from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Optional, Sequence

from ...storage import load_json_cache, save_json_cache

GITHUB_ISSUE_CACHE_NAMESPACE = "github-open-issues"
GITHUB_VIEWER_CONTEXT_CACHE_NAMESPACE = "github-viewer-context"
GITHUB_CACHE_PROVIDER = "gh-cli"
DEFAULT_GITHUB_ISSUE_CACHE_SECONDS = 300
DEFAULT_GITHUB_VIEWER_CONTEXT_CACHE_SECONDS = 1800


def load_cached_issue_payload(cache_key: str, ttl_seconds: int) -> Optional[list[dict[str, Any]]]:
    return _load_cached_payload(
        namespace=GITHUB_ISSUE_CACHE_NAMESPACE,
        cache_key=cache_key,
        ttl_seconds=ttl_seconds,
    )


def load_stale_issue_payload(cache_key: str) -> Optional[list[dict[str, Any]]]:
    return _load_cached_payload(
        namespace=GITHUB_ISSUE_CACHE_NAMESPACE,
        cache_key=cache_key,
        ttl_seconds=None,
        allow_stale=True,
    )


def save_issue_payload(
    cache_key: str,
    scope_hash: str,
    ttl_seconds: int,
    payload: Sequence[dict[str, Any]],
) -> None:
    _save_cached_payload(
        namespace=GITHUB_ISSUE_CACHE_NAMESPACE,
        cache_key=cache_key,
        scope_hash=scope_hash,
        ttl_seconds=ttl_seconds,
        payload=list(payload),
        metadata={"issue_count": len(payload)},
    )


def load_cached_viewer_context_payload(cache_key: str, ttl_seconds: int) -> Optional[dict[str, Any]]:
    payload = _load_cached_payload(
        namespace=GITHUB_VIEWER_CONTEXT_CACHE_NAMESPACE,
        cache_key=cache_key,
        ttl_seconds=ttl_seconds,
    )
    if isinstance(payload, dict):
        return payload
    return None


def load_stale_viewer_context_payload(cache_key: str) -> Optional[dict[str, Any]]:
    payload = _load_cached_payload(
        namespace=GITHUB_VIEWER_CONTEXT_CACHE_NAMESPACE,
        cache_key=cache_key,
        ttl_seconds=None,
        allow_stale=True,
    )
    if isinstance(payload, dict):
        return payload
    return None


def save_viewer_context_payload(
    cache_key: str,
    ttl_seconds: int,
    payload: dict[str, Any],
) -> None:
    _save_cached_payload(
        namespace=GITHUB_VIEWER_CONTEXT_CACHE_NAMESPACE,
        cache_key=cache_key,
        scope_hash=build_github_cache_key("viewer-context"),
        ttl_seconds=ttl_seconds,
        payload=payload,
        metadata={"viewer_login": payload.get("viewer_login", "")},
    )


def build_github_cache_key(*parts: str) -> str:
    normalized = json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))
    return sha256(normalized.encode("utf-8")).hexdigest()


def _load_cached_payload(
    namespace: str,
    cache_key: str,
    ttl_seconds: Optional[int],
    allow_stale: bool = False,
) -> Optional[Any]:
    if ttl_seconds is not None and ttl_seconds <= 0:
        return None

    try:
        entry = load_json_cache(
            namespace=namespace,
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            allow_stale=allow_stale,
        )
    except Exception:
        return None

    if entry is None:
        return None

    return entry.payload


def _save_cached_payload(
    namespace: str,
    cache_key: str,
    scope_hash: str,
    ttl_seconds: int,
    payload: Any,
    metadata: dict[str, Any],
) -> None:
    if ttl_seconds <= 0:
        return

    try:
        save_json_cache(
            namespace=namespace,
            cache_key=cache_key,
            provider=GITHUB_CACHE_PROVIDER,
            range_start=None,
            range_end=None,
            scope_hash=scope_hash,
            ttl_seconds=ttl_seconds,
            payload=payload,
            metadata=metadata,
        )
    except Exception:
        return
