from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import time
from typing import Optional

from .models import CalendarQueryResult


def load_calendar_cache(cache_key: str, ttl_seconds: int) -> Optional[CalendarQueryResult]:
    if ttl_seconds <= 0:
        return None

    cache_path = _cache_path(cache_key)
    if not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, (int, float)) or expires_at < time.time():
        return None

    data = payload.get("result")
    if not isinstance(data, dict):
        return None

    try:
        return CalendarQueryResult.from_dict(data)
    except Exception:
        return None


def save_calendar_cache(
    cache_key: str,
    ttl_seconds: int,
    result: CalendarQueryResult,
) -> None:
    if ttl_seconds <= 0:
        return

    cache_path = _cache_path(cache_key)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "expires_at": time.time() + ttl_seconds,
            "result": result.to_dict(),
        }
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        return


def build_calendar_cache_key(*parts: str) -> str:
    normalized = "::".join(parts)
    return sha256(normalized.encode("utf-8")).hexdigest()


def _cache_path(cache_key: str) -> Path:
    repo_root = os.getenv("YULE_REPO_ROOT")
    if repo_root:
        base_dir = Path(repo_root)
    else:
        base_dir = Path.cwd()
    return base_dir / ".cache" / "yule" / "calendar" / f"{cache_key}.json"
