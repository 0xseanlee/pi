import asyncio
import io
import logging
from pathlib import Path
import tempfile
import time
import contextlib

import discord
from discord import app_commands

from .config import ConfigError
from .engine import EngineError, transform
from .updater import lock

MAX_SOURCE = 2 * 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
ATTRIBUTION = 'Based on Prometheus by Elias Oelschner, https://github.com/prometheus-lua/Prometheus'


def progress_embed(stage, started, filename, *, detail='', outcome=None):
    color = discord.Color.green() if outcome is True else discord.Color.red() if outcome is False else discord.Color.blurple()
    embed = discord.Embed(title='OBF · VM 混淆', description=detail or '依實際處理階段更新；引擎未提供百分比。', color=color)
    embed.add_field(name='階段', value=stage, inline=True)
    embed.add_field(name='耗時', value=f'{max(0, int(time.monotonic() - started))} 秒', inline=True)
    embed.add_field(name='檔案', value=discord.utils.escape_markdown(filename[:150]), inline=False)
    embed.set_footer(text=ATTRIBUTION)
    return embed


class OBFClient(discord.Client):
    def __init__(self, configuration):
        super().__init__(intents=discord.Intents.default(), allowed_mentions=discord.AllowedMentions.none())
        self.configuration = configuration
        self.tree = app_commands.CommandTree(self)
        self.busy = False
        self.outcome = 0
        self.tree.add_command(app_commands.Command(
            name='obf', description='上傳 .lua 檔進行 VM 混淆；本次工作結束後 bot 下線。', callback=self.obfuscate,
        ))
        self.tree.add_command(app_commands.Command(
            name='obf_status', description='查看本次 bot 與混淆引擎狀態。', callback=self.status,
        ))

    async def setup_hook(self):
        if self.application_id != self.configuration['application_id']:
            raise ConfigError('bot 與已驗證的設定不符，已停止。')
        # Upsert only these command names; never bulk-delete unrelated app commands.
        for command in self.tree.get_commands():
            await self.http.upsert_global_command(self.application_id, command.to_dict(self.tree))

    async def on_ready(self):
        print('OBF 已上線。請在 Discord 使用 /obf 並上傳 .lua。Ctrl+C 可取消。', flush=True)
        if not self.configuration.get('engine_argv'):
            print('目前 VM 引擎尚未接上：/obf 會明確回報未就緒。', flush=True)

    async def authorize(self, interaction):
        if interaction.user.id == self.configuration['owner_id']:
            return True
        await interaction.response.send_message('這個 bot 僅限擁有者使用。', ephemeral=True)
        return False

    async def status(self, interaction: discord.Interaction):
        if not await self.authorize(interaction):
            return
        state = '已設定外部引擎，執行結果仍需驗證' if self.configuration.get('engine_argv') else 'VM 混淆引擎尚未接上'
        await interaction.response.send_message('按需單次模式。' + state, ephemeral=True)

    async def obfuscate(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self.authorize(interaction):
            return
        if self.busy:
            await interaction.response.send_message('本次已有一份工作處理中。', ephemeral=True)
            return
        if not file.filename.lower().endswith('.lua') or file.size > MAX_SOURCE:
            await interaction.response.send_message('請上傳不超過 2 MiB 的 .lua 原始檔。', ephemeral=True)
            return
        self.busy = True
        started = time.monotonic()
        state = {'stage': '接收檔案'}
        ticker = None

        async def update():
            while True:
                await asyncio.sleep(3)
                try:
                    await interaction.edit_original_response(embed=progress_embed(state['stage'], started, file.filename))
                except discord.HTTPException:
                    return

        async def stop_ticker():
            if ticker is not None:
                ticker.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await ticker

        try:
            await interaction.response.defer(thinking=True)
            await interaction.edit_original_response(embed=progress_embed(state['stage'], started, file.filename))
            if not self.configuration.get('engine_argv'):
                raise EngineError('VM 混淆引擎尚未接上，本次沒有讀取或處理原碼。')
            ticker = asyncio.create_task(update())
            source_bytes = await asyncio.wait_for(file.read(), timeout=30)
            state['stage'] = '檢查內容'
            if len(source_bytes) > MAX_SOURCE or b'\0' in source_bytes:
                raise EngineError('原始檔內容或大小不符合限制。')
            try:
                source_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                raise EngineError('請提供 UTF-8 的 Lua 原始檔。') from None
            with tempfile.TemporaryDirectory(prefix='dc-obf-') as directory:
                source = Path(directory) / 'input.lua'
                source.write_bytes(source_bytes)
                state['stage'] = 'VM 混淆中'
                await interaction.edit_original_response(embed=progress_embed(state['stage'], started, file.filename))
                output = await transform(self.configuration['engine_argv'], source, Path(directory) / 'protected.lua')
                if output.stat().st_size > min(MAX_OUTPUT, interaction.filesize_limit):
                    raise EngineError('輸出檔超過本次 Discord 回傳限制。')
                await stop_ticker()
                await interaction.edit_original_response(
                    embed=progress_embed('完成', started, file.filename, outcome=True,
                                         detail='已產生 VM 混淆檔。本次 bot 即將下線；請在你的注入器測試相容性。'),
                    attachments=[discord.File(io.BytesIO(output.read_bytes()), filename='protected.lua')],
                )
        except EngineError as error:
            self.outcome = 1
            await stop_ticker()
            await interaction.edit_original_response(embed=progress_embed('失敗', started, file.filename, detail=str(error), outcome=False))
        except Exception:
            self.outcome = 1
            await stop_ticker()
            await interaction.edit_original_response(embed=progress_embed('失敗', started, file.filename,
                                                       detail='本次處理未完成，未回傳產物；bot 即將下線。', outcome=False))
        finally:
            await stop_ticker()
            await self.close()


def run(configuration):
    async def session():
        async with OBFClient(configuration) as client:
            await client.start(configuration['token'])
            return client.outcome
    logging.getLogger('discord').setLevel(logging.WARNING)
    try:
        with lock('obf.run.lock'):
            return asyncio.run(session())
    except discord.LoginFailure:
        raise ConfigError('Discord token 已失效，請重新執行 dc obf --setup。') from None
