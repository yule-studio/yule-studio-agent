from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

import unittest

import yule_orchestrator.discord.commands as discord_commands


class DiscordCommandsTestCase(unittest.TestCase):
    def test_bind_discord_runtime_globals_sets_module_globals(self) -> None:
        fake_discord = object()
        fake_app_commands = object()
        sentinel = object()
        previous_discord = discord_commands.__dict__.get("discord", sentinel)
        previous_app_commands = discord_commands.__dict__.get("app_commands", sentinel)

        try:
            discord_commands._bind_discord_runtime_globals(
                discord_module=fake_discord,
                app_commands_module=fake_app_commands,
            )

            self.assertIs(discord_commands.__dict__["discord"], fake_discord)
            self.assertIs(discord_commands.__dict__["app_commands"], fake_app_commands)
        finally:
            if previous_discord is sentinel:
                discord_commands.__dict__.pop("discord", None)
            else:
                discord_commands.__dict__["discord"] = previous_discord

            if previous_app_commands is sentinel:
                discord_commands.__dict__.pop("app_commands", None)
            else:
                discord_commands.__dict__["app_commands"] = previous_app_commands
