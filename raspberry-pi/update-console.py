#!/usr/bin/env python3
"""Update the UI and HTTP API without changing networking, TLS or authentication."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request

if os.geteuid() != 0:
    raise SystemExit('請使用 sudo 執行')
version = sys.argv[1]
base = 'https://raw.githubusercontent.com/0xseanlee/pi/' + version + '/'
backup = Path('/var/backups/pi-station') / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
backup.mkdir(parents=True, mode=0o700)
records = []
try:
    with urllib.request.urlopen(base + 'raspberry-pi/console-manifest.json', timeout=30) as r:
        manifest = json.load(r)
    selected = ['index.html', 'style.css', 'app.js', 'control.js', 'raspberry-pi/device-server.py']
    downloads = []
    for source in selected:
        with urllib.request.urlopen(base + source, timeout=30) as r:
            content = r.read()
        info = manifest[source]
        if hashlib.sha256(content).hexdigest() != info['sha256']:
            raise RuntimeError('校驗失敗：' + source)
        if source.endswith('.py'):
            compile(content, source, 'exec')
        downloads.append((Path(info['destination']), content))
    for target, content in downloads:
        existed = target.exists()
        saved = backup / str(target).lstrip('/')
        if existed:
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        records.append((str(target), existed))
        (backup / 'files.json').write_text(json.dumps(records))
        target.write_bytes(content)
        target.chmod(0o644)
    subprocess.run(['systemctl', 'restart', 'pi-station-device.service'], check=True)
    context = ssl.create_default_context(cafile='/etc/pi-station/server.crt')
    for attempt in range(10):
        try:
            with urllib.request.urlopen('https://127.0.0.1:8443/api/v1/discovery', context=context, timeout=3) as r:
                if json.load(r).get('service') != 'pi-station':
                    raise RuntimeError('服務識別不符')
            break
        except Exception:
            if attempt == 9:
                raise
            time.sleep(1)
    print('更新成功。')
    print('備份：' + str(backup))
    print('入口：https://0xseanlee.github.io/pi/')
    print('裝置位址：https://10.100.7.67:8443')
except Exception as error:
    print('更新失敗：' + str(error))
    for name, existed in reversed(records):
        target = Path(name)
        if existed:
            shutil.copy2(backup / name.lstrip('/'), target)
        else:
            target.unlink(missing_ok=True)
    subprocess.run(['systemctl', 'restart', 'pi-station-device.service'])
    print('已嘗試恢復原版本。')
    raise SystemExit(1)
