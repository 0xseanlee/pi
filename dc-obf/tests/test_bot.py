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

    async def test_template_channels_keep_sources_outputs_and_progress(self):
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        cfg = self.configuration()
        cfg['engine_argv'] = ['test-engine']
        client = OBFClient(cfg)
        client.close = AsyncMock()
        interaction = types.SimpleNamespace(id=42, user=types.SimpleNamespace(id=cfg['owner_id']),
            response=types.SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(), filesize_limit=1024 * 1024)
        original = b'print("my source")'
        attachment = types.SimpleNamespace(filename='../../original.lua', size=len(original), read=AsyncMock(return_value=original))
        progress = types.SimpleNamespace(jump_url='https://discord.com/channels/1/2/3', edit=AsyncMock())
        source_message = types.SimpleNamespace(jump_url='https://discord.com/channels/1/4/5')
        result = types.SimpleNamespace(jump_url='https://discord.com/channels/1/6/7')
        channels = {'upload': types.SimpleNamespace(send=AsyncMock(return_value=source_message)),
                    'processing': types.SimpleNamespace(send=AsyncMock(return_value=progress)),
                    'done': types.SimpleNamespace(send=AsyncMock(return_value=result),
                                                  guild=types.SimpleNamespace(filesize_limit=1024 * 1024))}
        async def transform(argv, source, output):
            self.assertEqual(source.read_bytes(), original)
            output.write_bytes(b'-- test protected output\nreturn 1')
            return output
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.archive.Path.home', return_value=Path(root)), patch.object(
            client, 'job_channels', return_value=channels), patch('dc_obf.bot.transform', side_effect=transform):
            await client.obfuscate(interaction, attachment)
            jobs = list((Path(root)/'.local/share/dc-obf/jobs').iterdir())
            self.assertEqual(len(jobs), 1)
            job = jobs[0]
            self.assertEqual((job/'input.lua').read_bytes(), original)
            self.assertTrue((job/'protected.lua').exists())
            self.assertEqual(job.stat().st_mode & 0o777, 0o700)
            self.assertEqual((job/'input.lua').stat().st_mode & 0o777, 0o600)
            self.assertEqual((job/'protected.lua').stat().st_mode & 0o777, 0o600)
            saved = json.loads((job/'job.json').read_text())
            self.assertEqual(saved['status'], 'done')
            self.assertEqual(saved['result_url'], result.jump_url)
            self.assertEqual(len(saved['source_sha256']), 64)
            channels['upload'].send.assert_awaited_once()
            channels['processing'].send.assert_awaited_once()
            channels['done'].send.assert_awaited_once()
            client.close.assert_awaited_once()
            self.assertEqual(client.outcome, 0)

    async def test_failed_engine_keeps_source_and_failure_record(self):
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from dc_obf.engine import EngineError
        cfg = self.configuration()
        cfg['engine_argv'] = ['test-engine']
        client = OBFClient(cfg)
        client.close = AsyncMock()
        interaction = types.SimpleNamespace(id=43, user=types.SimpleNamespace(id=cfg['owner_id']),
            response=types.SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock())
        attachment = types.SimpleNamespace(filename='source.lua', size=10, read=AsyncMock(return_value=b'return 123'))
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.archive.Path.home', return_value=Path(root)), patch(
            'dc_obf.bot.transform', side_effect=EngineError('引擎失敗')):
            await client.obfuscate(interaction, attachment)
            job = next((Path(root)/'.local/share/dc-obf/jobs').iterdir())
            self.assertEqual((job/'input.lua').read_bytes(), b'return 123')
            saved = json.loads((job/'job.json').read_text())
            self.assertEqual(saved['status'], 'failed')
            self.assertEqual(saved['error'], '引擎失敗')
            self.assertEqual(client.outcome, 1)
            client.close.assert_awaited_once()

    async def test_incomplete_template_rejects_without_consuming_job(self):
        cfg = self.configuration()
        cfg['server'] = {'guild_id': 1}
        client = OBFClient(cfg)
        interaction = types.SimpleNamespace(user=types.SimpleNamespace(id=cfg['owner_id']),
            response=types.SimpleNamespace(send_message=AsyncMock()))
        attachment = types.SimpleNamespace(filename='source.lua', size=10, read=AsyncMock())
        await client.obfuscate(interaction, attachment)
        self.assertFalse(client.busy)
        attachment.read.assert_not_awaited()
        await client.close()

    async def test_output_survives_discord_delivery_failure(self):
        import json
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        import discord
        cfg = self.configuration()
        cfg['engine_argv'] = ['test-engine']
        client = OBFClient(cfg)
        client.close = AsyncMock()
        interaction = types.SimpleNamespace(id=44, user=types.SimpleNamespace(id=cfg['owner_id']),
            response=types.SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            edit_original_response=AsyncMock(), filesize_limit=1024 * 1024)
        attachment = types.SimpleNamespace(filename='source.lua', size=10, read=AsyncMock(return_value=b'return 123'))
        async def transform(argv, source, output):
            output.write_bytes(b'-- preserved output\nreturn 123')
            return output
        # Simulate a successful initial progress edit followed by a failed upload.
        interaction.edit_original_response.side_effect = [None, None,
            discord.HTTPException(types.SimpleNamespace(status=413, reason='Payload Too Large'), 'test'), None]
        with tempfile.TemporaryDirectory() as root, patch('dc_obf.archive.Path.home', return_value=Path(root)), patch(
            'dc_obf.bot.transform', side_effect=transform):
            await client.obfuscate(interaction, attachment)
            job = next((Path(root)/'.local/share/dc-obf/jobs').iterdir())
            self.assertTrue((job/'input.lua').exists())
            self.assertEqual((job/'protected.lua').read_bytes(), b'-- preserved output\nreturn 123')
            saved = json.loads((job/'job.json').read_text())
            self.assertEqual(saved['status'], 'failed')
            self.assertIn('output_sha256', saved)
            self.assertEqual(client.outcome, 1)
            client.close.assert_awaited_once()
