import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ConfigError(Exception):
    pass


def config_path():
    return Path.home() / '.config/dc/obf.json'


def private_write(path, content):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, temporary = tempfile.mkstemp(prefix='.obf-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def private_read(path):
    mode = path.lstat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_mode & 0o077 or mode.st_uid != os.getuid():
        raise ConfigError('私人設定檔必須由本帳號持有，且權限為 0600。')
    return path.read_text()


def load_config():
    path = config_path()
    if not path.exists():
        raise ConfigError('請先執行 dc obf --setup。')
    try:
        data = json.loads(private_read(path))
        if not isinstance(data, dict) or not data.get('token'):
            raise ValueError()
        if int(data.get('application_id', 0)) <= 0 or int(data.get('owner_id', 0)) <= 0:
            raise ValueError()
        return data
    except (ValueError, TypeError):
        raise ConfigError('設定不完整，請重新執行 dc obf --setup。') from None


def validate_token(token):
    request = Request('https://discord.com/api/v10/oauth2/applications/@me', headers={
        'Authorization': 'Bot ' + token, 'User-Agent': 'DC-OBF/0.1',
    })
    try:
        with urlopen(request, timeout=20) as response:
            data = json.load(response)
    except HTTPError as error:
        raise ConfigError(f'Discord 驗證失敗（HTTP {error.code}）。token 已私人暫存，可重跑設定。') from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ConfigError('無法完成 Discord 驗證。token 已私人暫存，可重跑設定。') from None
    owner = (data.get('team') or {}).get('owner_user_id') or (data.get('owner') or {}).get('id')
    try:
        application_id, owner_id = int(data['id']), int(owner)
        if application_id <= 0 or owner_id <= 0:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ConfigError('Discord 未回傳可確認的應用程式擁有者，設定尚未啟用。') from None
    return {'application_id': application_id, 'owner_id': owner_id}


def save_token(token):
    token = token.strip()
    if token.startswith('Bot '):
        token = token[4:].strip()
    if not token or len(token) > 4096 or any(c.isspace() for c in token):
        raise ConfigError('請貼上有效的 Discord bot token。')
    path = config_path()
    pending = path.with_suffix('.token')
    # Keep a failed-network attempt private so the user need not retrieve it again.
    private_write(pending, token)
    identity = validate_token(token)
    previous = load_config() if path.exists() else {}
    configuration = {**identity, 'token': token, 'engine_argv': previous.get('engine_argv') or [
        '{python}', '-m', 'dc_obf.prometheus_adapter', '{input}', '{output}',
    ]}
    if previous.get('application_id') == identity['application_id'] and previous.get('server'):
        configuration['server'] = previous['server']
    private_write(path, json.dumps(configuration) + '\n')
    pending.unlink(missing_ok=True)
    return configuration


def saved_token():
    pending = config_path().with_suffix('.token')
    if pending.exists():
        return private_read(pending).strip()
    return load_config()['token'] if config_path().exists() else ''


def invite_url(application_id, *, manage_channels=False):
    return 'https://discord.com/oauth2/authorize?' + urlencode({
        'client_id': application_id, 'scope': 'bot applications.commands',
        'permissions': 117776 if manage_channels else 117760,
    })
