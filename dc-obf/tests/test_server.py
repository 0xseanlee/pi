import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from dc_obf.config import ConfigError, config_path
from dc_obf.server import ensure_template


class ServerTests(unittest.IsolatedAsyncioTestCase):
    def guild(self):
        guild = MagicMock()
        guild.id, guild.owner_id = 123, 456
        guild.me = MagicMock()
        guild.me.guild_permissions.manage_channels = True
        owner = MagicMock()
        owner.id = 456
        guild.get_member.return_value = owner
        guild.get_channel.return_value = None
        guild.categories = []
        category = MagicMock(spec=discord.CategoryChannel)
        category.id, category.name, category.text_channels = 789, 'dc-obf', []
        category.overwrites_for.return_value = discord.PermissionOverwrite(view_channel=False)
        guild.create_category = AsyncMock(return_value=category)

        async def create_text(name, **kwargs):
            channel = MagicMock(spec=discord.TextChannel)
            channel.name, channel.id, channel.topic = name, 1000 + len(category.text_channels), kwargs['topic']
            channel.permissions_for.return_value = types.SimpleNamespace(
                view_channel=True, send_messages=True, attach_files=True, embed_links=True)
            category.text_channels.append(channel)
            return channel
        guild.create_text_channel = AsyncMock(side_effect=create_text)
        return guild, category, owner

    async def test_template_is_private_and_rerun_keeps_channels_and_history(self):
        guild, category, owner = self.guild()
        cfg = {'application_id': 1, 'owner_id': 456, 'token': 'unit-test-placeholder'}
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.config.Path.home', return_value=Path(root)):
            first = (await ensure_template(guild, cfg)).copy()
            overwrites = guild.create_category.call_args.kwargs['overwrites']
            self.assertFalse(overwrites[guild.default_role].view_channel)
            self.assertTrue(overwrites[owner].view_channel)
            guild.get_channel.return_value = category
            second = await ensure_template(guild, cfg)
            self.assertEqual(first, second)
            guild.create_category.assert_awaited_once()
            self.assertEqual(guild.create_text_channel.await_count, 3)
            self.assertEqual(json.loads(config_path().read_text())['server']['done'], first['done'])
            self.assertEqual(config_path().stat().st_mode & 0o777, 0o600)

    async def test_missing_permission_stops_before_mutation(self):
        guild, _, _ = self.guild()
        guild.me.guild_permissions.manage_channels = False
        with self.assertRaisesRegex(ConfigError, '管理頻道'):
            await ensure_template(guild, {'application_id': 1, 'owner_id': 456})
        guild.create_category.assert_not_awaited()
        guild.create_text_channel.assert_not_awaited()

    async def test_interrupted_template_resumes_without_duplicates(self):
        guild, category, _ = self.guild()
        cfg = {'application_id': 1, 'owner_id': 456, 'token': 'unit-test-placeholder'}
        original = guild.create_text_channel.side_effect

        async def interrupted(name, **kwargs):
            if name == 'processing':
                raise RuntimeError('simulated disconnect')
            return await original(name, **kwargs)
        guild.create_text_channel.side_effect = interrupted
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.config.Path.home', return_value=Path(root)):
            with self.assertRaises(RuntimeError):
                await ensure_template(guild, cfg)
            self.assertIn('upload', json.loads(config_path().read_text())['server'])
            guild.get_channel.return_value = category
            guild.create_text_channel.side_effect = original
            await ensure_template(guild, cfg)
            self.assertEqual(len(category.text_channels), 3)
            guild.create_category.assert_awaited_once()
