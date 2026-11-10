import time
import types
import unittest
from unittest.mock import AsyncMock

from dc_obf.bot import OBFClient, progress_embed


class BotTests(unittest.IsolatedAsyncioTestCase):
    def configuration(self):
        return {'application_id': 123456789012345678, 'owner_id': 234567890123456789, 'token': 'unused', 'engine_argv': []}

    async def test_command_accepts_attachment_named_file(self):
        client = OBFClient(self.configuration())
        command = client.tree.get_command('obf')
        self.assertIsNotNone(command)
        data = command.to_dict(client.tree)
        self.assertEqual(data['options'][0]['name'], 'file')
        self.assertEqual(data['options'][0]['type'], 11)
        await client.close()

    async def test_unconfigured_engine_does_not_read_source_and_exits(self):
        client = OBFClient(self.configuration())
        interaction = types.SimpleNamespace(user=types.SimpleNamespace(id=self.configuration()['owner_id']),
            response=types.SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()), edit_original_response=AsyncMock())
        attachment = types.SimpleNamespace(filename='source.lua', size=20, read=AsyncMock())
        client.close = AsyncMock()
        await client.obfuscate(interaction, attachment)
        attachment.read.assert_not_awaited()
        client.close.assert_awaited_once()
        self.assertEqual(client.outcome, 1)
        embed = interaction.edit_original_response.call_args.kwargs['embed']
        self.assertIn('失敗', embed.fields[0].value)

    async def test_progress_is_real_stage_and_elapsed_time_not_fake_percent(self):
        embed = progress_embed('VM 混淆中', time.monotonic() - 5, 'input.lua')
        text = str(embed.to_dict())
        self.assertIn('VM 混淆中', text)
        self.assertIn('5 秒', text)
        self.assertNotIn('50%', text)
