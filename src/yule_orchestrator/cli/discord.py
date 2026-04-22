from __future__ import annotations

from pathlib import Path


def run_discord_bot_command(repo_root: Path) -> int:
    try:
        from ..discord.bot import run_discord_bot
    except ImportError as exc:
        raise ValueError(
            "discord.py is required to run the Discord bot. Install project dependencies again with `python -m pip install -e .`."
        ) from exc

    run_discord_bot(repo_root=repo_root)
    return 0
