import asyncio
import logging
import time
import contextlib

import discord
from discord import app_commands

from .config import ConfigError
from .archive import Job
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

    def job_channels(self, interaction):
        server = self.configuration.get('server')
        if not server:
            return None
        if not all(server.get(key) for key in ('guild_id', 'upload', 'processing', 'done')):
            raise EngineError('模板尚未完成，請重新執行 dc obf --setupserver。')
        if (getattr(interaction, 'guild_id', None) != server['guild_id'] or
                getattr(interaction, 'channel_id', None) != server.get('upload')):
            raise EngineError(f"請在 <#{server.get('upload', 0)}> 使用 /obf。")
        channels = {name: self.get_channel(server.get(name, 0)) for name in ('upload', 'processing', 'done')}
        if not all(isinstance(ch, discord.TextChannel) and ch.guild.id == server['guild_id']
                   for ch in channels.values()):
            raise EngineError('模板頻道不完整，請重新執行 dc obf --setupserver。')
        return channels

    async def obfuscate(self, interaction: discord.Interaction, file: discord.Attachment):
        if not await self.authorize(interaction):
            return
        if self.busy:
            await interaction.response.send_message('本次已有一份工作處理中。', ephemeral=True)
            return
        try:
            channels = self.job_channels(interaction)
        except EngineError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        if not file.filename.lower().endswith('.lua') or file.size > MAX_SOURCE:
            await interaction.response.send_message('混淆引擎目前接受不超過 2 MiB 的 .lua 原始檔。', ephemeral=True)
            return
        self.busy = True
        started = time.monotonic()
        state = {'stage': '接收檔案'}
        ticker = None
        progress = None
        job = None

        def embed(stage, **kwargs):
            result = progress_embed(stage, started, file.filename, **kwargs)
            if job:
                result.add_field(name='工作 ID', value=job.id, inline=False)
            return result

        async def edit_progress(value):
            if progress is not None:
                await progress.edit(embed=value)
            else:
                await interaction.edit_original_response(embed=value)

        async def update():
            while True:
                await asyncio.sleep(3)
                try:
                    await edit_progress(embed(state['stage']))
                except discord.HTTPException:
                    return

        async def stop_ticker():
            if ticker is not None:
                ticker.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await ticker

        async def fail(detail, status='failed'):
            self.outcome = 1
            await stop_ticker()
            if job:
                job.record(status=status, error=detail)
                detail += f' 工作 {job.id} 中已保存的檔案與紀錄保留在 Pi。'
            failed = embed('失敗', detail=detail, outcome=False)
            # A channel/network failure must not mask the saved job or prevent exit.
            with contextlib.suppress(discord.HTTPException):
                await edit_progress(failed)
            if channels:
                with contextlib.suppress(discord.HTTPException):
                    message = await channels['done'].send(embed=failed)
                    if job:
                        job.record(result_url=message.jump_url)

        try:
            await interaction.response.defer(thinking=True)
            if not self.configuration.get('engine_argv'):
                raise EngineError('VM 混淆引擎尚未接上，本次沒有讀取或處理原碼。')
            job = Job(file.filename, interaction.id)
            if channels:
                progress = await channels['processing'].send(embed=embed(state['stage']))
                job.record(progress_url=progress.jump_url)
                await interaction.edit_original_response(content=f'已接收工作 {job.id}。進度：{progress.jump_url}')
            else:
                await edit_progress(embed(state['stage']))
            ticker = asyncio.create_task(update())
            source_bytes = await asyncio.wait_for(file.read(), timeout=30)
            job.save_source(source_bytes)
            state['stage'] = '檢查內容'
            # The stored name is fixed, never derived from the attachment path.
            if channels and len(source_bytes) <= MAX_SOURCE:
                with contextlib.closing(discord.File(job.source, filename='input.lua')) as source_file:
                    message = await channels['upload'].send(
                        content=f'工作 {job.id} · 原始檔備份', file=source_file)
                job.record(source_url=message.jump_url)
            if len(source_bytes) > MAX_SOURCE or b'\0' in source_bytes:
                raise EngineError('原始檔內容或大小不符合限制。')
            try:
                source_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                raise EngineError('請提供 UTF-8 的 Lua 原始檔。') from None
            state['stage'] = 'VM 混淆中'
            job.record(status='processing')
            await edit_progress(embed(state['stage']))
            output = await transform(self.configuration['engine_argv'], job.source, job.output)
            job.finish_output()
            # Normal channel sends use the guild limit; interaction responses use
            # Discord's per-interaction limit, which may differ with user Nitro.
            limit = channels['done'].guild.filesize_limit if channels else interaction.filesize_limit
            if output.stat().st_size > min(MAX_OUTPUT, limit):
                raise EngineError('產物已保存在 Pi，但超過此頻道的回傳限制，未上傳 Discord。')
            await stop_ticker()
            complete = embed('完成', outcome=True,
                             detail='原檔與產物已保存在 Pi。本次 bot 即將下線；請在你的注入器測試相容性。')
            if channels:
                if job.data.get('source_url'):
                    complete.add_field(name='原始檔', value=job.data['source_url'], inline=False)
                with contextlib.closing(discord.File(output, filename='protected.lua')) as result_file:
                    message = await channels['done'].send(embed=complete, file=result_file)
                job.record(status='done', result_url=message.jump_url)
                # Result delivery has already succeeded; a stale interaction or
                # unavailable progress message must not relabel this job failed.
                with contextlib.suppress(discord.HTTPException):
                    await edit_progress(embed('完成', outcome=True, detail=f'產物與紀錄：{message.jump_url}'))
                with contextlib.suppress(discord.HTTPException):
                    await interaction.edit_original_response(content=f'工作 {job.id} 完成：{message.jump_url}')
            else:
                with contextlib.closing(discord.File(output, filename='protected.lua')) as result_file:
                    await interaction.edit_original_response(embed=complete, attachments=[result_file])
                job.record(status='done')
        except asyncio.CancelledError:
            if job:
                job.record(status='cancelled')
            raise
        except EngineError as error:
            await fail(str(error))
        except Exception:
            await fail('本次處理或 Discord 傳送未完成；bot 即將下線。')
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
