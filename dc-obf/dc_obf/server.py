import asyncio
import json
import sys

import discord

from .config import ConfigError, config_path, invite_url, private_write
from .updater import lock

CHANNELS = {
    'upload': '在此使用 /obf，file 選 .lua 或 .lua.txt；保留每次原始檔。',
    'processing': '每份工作以同一則嵌入訊息更新實際階段與耗時。',
    'done': '保留混淆產物、完成與失敗紀錄；bot 處理一份後下線。',
}
MARKER = 'DC OBF template v1 | '


async def ensure_template(guild, configuration):
    me = guild.me
    permissions = me.guild_permissions
    if not permissions.manage_channels:
        raise ConfigError('Bot 需要「管理頻道」權限才能套模板。請用此連結重新授權後重試：\n' +
                          invite_url(configuration['application_id'], manage_channels=True))
    owner = guild.get_member(configuration['owner_id']) or await guild.fetch_member(configuration['owner_id'])
    if owner.id != guild.owner_id and not owner.guild_permissions.manage_guild:
        raise ConfigError('請選擇你擁有或具有「管理伺服器」權限的伺服器。')
    saved = configuration.get('server', {})
    category = guild.get_channel(saved.get('category_id', 0)) if saved.get('guild_id') == guild.id else None
    if category is not None and not isinstance(category, discord.CategoryChannel):
        raise ConfigError('保存的分類已改變，請先檢查 Discord 頻道設定。')
    if category is None:
        # Adopt only this tool's marked category; unrelated same-name channels stay untouched.
        category = next((c for c in guild.categories if c.name == 'dc-obf' and
                         any((getattr(ch, 'topic', '') or '').startswith(MARKER) for ch in c.channels)), None)
    if category is None:
        category = await guild.create_category('dc-obf', overwrites={
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            owner: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                               read_message_history=True, use_application_commands=True),
            me: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True,
                                            embed_links=True, read_message_history=True),
        }, reason='dc obf --setupserver')
    if category.overwrites_for(guild.default_role).view_channel is not False:
        raise ConfigError('OBF 分類已開放給所有人，請先調整分類的檢視頻道權限再重試。')
    # Save immediately, so an interrupted setup can resume without duplicating the category.
    server = {'guild_id': guild.id, 'category_id': category.id}
    configuration['server'] = server
    private_write(config_path(), json.dumps(configuration) + '\n')
    for name, topic in CHANNELS.items():
        matches = [ch for ch in category.text_channels if ch.topic and ch.topic.startswith(MARKER + name + ' | ')]
        if len(matches) > 1:
            raise ConfigError(f'找到多個 {name} 模板頻道，請先保留一個再重試。')
        channel = matches[0] if matches else await guild.create_text_channel(
            name, category=category, topic=MARKER + name + ' | ' + topic, reason='dc obf --setupserver')
        effective = channel.permissions_for(me)
        if not all(getattr(effective, p) for p in ('view_channel', 'send_messages', 'attach_files', 'embed_links')):
            raise ConfigError(f'Bot 無法讀寫 {name}，請檢查該頻道權限後重試。')
        server[name] = channel.id
        private_write(config_path(), json.dumps(configuration) + '\n')
    return server


class TemplateClient(discord.Client):
    def __init__(self, configuration):
        super().__init__(intents=discord.Intents.default())
        self.configuration = configuration
        self.started = False
        self.error = None

    async def setup_hook(self):
        if self.application_id != self.configuration['application_id']:
            raise ConfigError('Bot 與已驗證設定不符，已停止。')

    async def on_ready(self):
        if self.started:
            return
        self.started = True
        try:
            guilds = list(self.guilds)
            if not guilds:
                raise ConfigError('Bot 尚未加入伺服器，請先使用此邀請連結：\n' +
                                  invite_url(self.configuration['application_id'], manage_channels=True))
            if len(guilds) == 1:
                guild = guilds[0]
            else:
                for candidate in guilds:
                    print(f'{candidate.id}  {candidate.name}', flush=True)
                selected = await asyncio.to_thread(input, '要套模板的伺服器 ID: ')
                guild = next((g for g in guilds if str(g.id) == selected.strip()), None)
                if guild is None:
                    raise ConfigError('未選到 Bot 所在的伺服器。')
            await ensure_template(guild, self.configuration)
            print(f'模板已就緒：{guild.name} → upload / processing / done。再次執行會沿用，保留紀錄。')
            print('設定完成，Bot 已下線；要處理檔案時執行 dc obf。')
        except ConfigError as error:
            self.error = error
        except discord.Forbidden:
            self.error = ConfigError('Discord 拒絕套模板，請檢查 Bot 的「管理頻道」與讀寫權限。')
        except Exception:
            self.error = ConfigError('模板設定未完成；已建立的頻道會保留，可重新執行。')
        finally:
            await self.close()


def setup_server(configuration):
    if not sys.stdin.isatty():
        raise ConfigError('請在互動終端機執行 dc obf --setupserver。')

    async def session():
        async with TemplateClient(configuration) as client:
            await client.start(configuration['token'])
            if client.error:
                raise client.error
        return 0
    try:
        with lock('obf.run.lock'):
            return asyncio.run(session())
    except discord.LoginFailure:
        raise ConfigError('Discord token 已失效，請重新執行 dc obf --setup。') from None
