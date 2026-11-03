#!/bin/sh
set -eu
[ "$(id -u)" = 0 ] || { echo '請使用 sudo 執行'; exit 1; }
version=${1:-main}
apt-get update
apt-get install -y python3-paramiko openssl polkitd
exec python3 - "$version" <<'PY'
import datetime, hashlib, json, os, pathlib, pwd, shutil, subprocess, sys, tempfile
import urllib.request

version = sys.argv[1]
base = 'https://raw.githubusercontent.com/0xseanlee/pi/' + version + '/'
P = pathlib.Path
account = pwd.getpwnam('sean')
home = account.pw_dir
backup = P('/var/backups/pi-station') / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
backup.mkdir(parents=True, mode=0o700)
records = []

def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()

def save(path):
    path = P(path)
    if any(old == str(path) for old, _ in records):
        return
    saved = backup / str(path).lstrip('/')
    exists = path.exists()
    if exists:
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
    records.append((str(path), exists))
    (backup / 'files.json').write_text(json.dumps(records))

def install(path, content, mode=0o644):
    path = P(path)
    save(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    path.chmod(mode)

def restore():
    for path, exists in reversed(records):
        target = P(path)
        if exists:
            shutil.copy2(backup / path.lstrip('/'), target)
        else:
            target.unlink(missing_ok=True)
    subprocess.run(['systemctl', 'daemon-reload'])
    for service in ('pi-station-auth', 'pi-station-device'):
        subprocess.run(['systemctl', 'restart', service])

try:
    print('下載並驗證網站與後端……', flush=True)
    with urllib.request.urlopen(base + 'raspberry-pi/console-manifest.json', timeout=30) as response:
        manifest = json.load(response)
    downloads = {}
    for source, info in manifest.items():
        with urllib.request.urlopen(base + source, timeout=30) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != info['sha256']:
            raise RuntimeError('檔案校驗失敗：' + source)
        if source.endswith('.py'):
            compile(content, source, 'exec')
        downloads[source] = content
    for source, content in downloads.items():
        install(manifest[source]['destination'], content)

    config = json.loads(P('/etc/pi-station-wifi.json').read_text())
    import uuid
    hotspot = str(uuid.UUID(config['uuid']))
    override = ('[Service]\nProtectHome=read-only\nReadWritePaths=' + home + '\n'
        'Environment=XDG_RUNTIME_DIR=/run/user/' + str(account.pw_uid) + '\n'
        'Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/' + str(account.pw_uid) + '/bus\n'
        'Environment=PI_STATION_HOTSPOT_UUID=' + hotspot + '\n')
    install('/etc/systemd/system/pi-station-device.service.d/console.conf', override)
    rule = '''polkit.addRule(function(action, subject) {
  if (subject.user === "sean" && action.id === "org.freedesktop.NetworkManager.settings.modify.system") {
    return polkit.Result.YES;
  }
});
'''
    install('/etc/polkit-1/rules.d/49-pi-station-network.rules', rule)
    run('loginctl', 'enable-linger', 'sean')
    run('systemctl', 'start', 'user@' + str(account.pw_uid) + '.service')

    # 加入目前學校 IP 與熱點位址，避免換網路後憑證缺少對應 SAN。
    addresses = json.loads(run('ip', '-j', '-4', 'address', 'show', 'dev', 'wlan0'))
    ips = {'127.0.0.1'} | {'172.20.10.' + str(n) for n in range(2, 15)}
    for interface in addresses:
        ips.update(item['local'] for item in interface.get('addr_info', []))
    san = 'DNS:sean.local,DNS:sean,' + ','.join('IP:' + ip for ip in sorted(ips))
    save('/etc/pi-station/server.crt')
    run('openssl', 'req', '-x509', '-new', '-key', '/etc/pi-station/server.key',
        '-out', '/etc/pi-station/server.crt', '-days', '365', '-subj', '/CN=sean.local',
        '-addext', 'subjectAltName=' + san)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'restart', 'pi-station-auth.service')
    run('systemctl', 'restart', 'pi-station-device.service')
    run('systemctl', 'is-active', 'pi-station-auth.service', 'pi-station-device.service')
    print('安裝成功。備份：' + str(backup))
    print(run('openssl', 'x509', '-in', '/etc/pi-station/server.crt', '-noout', '-fingerprint', '-sha256'))
    for ip in sorted(ips - {'127.0.0.1'}):
        if not ip.startswith('172.20.10.') or any(ip == a.get('local') for i in addresses for a in i.get('addr_info', [])):
            print('控制台：https://' + ip + ':8443/')
except Exception as error:
    print('安裝失敗：' + str(error))
    restore()
    print('已嘗試恢復更新前的檔案；套件安裝與 user linger 設定會保留。')
    raise SystemExit(1)
PY
