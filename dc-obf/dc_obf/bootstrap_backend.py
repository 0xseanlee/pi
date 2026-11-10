"""Install the pinned source backend without running installer scripts."""
from pathlib import Path
import shutil
import tarfile
import tempfile
from urllib.request import urlopen

COMMIT = 'a98c50165f2a53f6d765a82eee60dfea53803445'


def vendor_path():
    return Path.home() / '.local/lib/dc-obf/backends' / ('prometheus-' + COMMIT)


def ensure_backend():
    target = vendor_path()
    if (target / 'cli.lua').is_file() and (target / '.source-commit').read_text().strip() == COMMIT:
        return target
    if not (shutil.which('lua5.1') or shutil.which('luajit')):
        raise RuntimeError('Pi 需要 lua5.1 或 luajit 才能使用目前的 VM 後端。')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.backend-', dir=target.parent) as temporary:
        root = Path(temporary)
        destination = root / 'source'
        old = Path.home() / '.local/lib/dc-obf/prometheus'
        if (old / '.source-commit').is_file() and (old / '.source-commit').read_text().strip() == COMMIT:
            shutil.copytree(old, destination)
        else:
            destination.mkdir()
            with urlopen('https://api.github.com/repos/prometheus-lua/Prometheus/tarball/' + COMMIT, timeout=30) as response:
                archive = response.read(12 * 1024 * 1024 + 1)
            if len(archive) > 12 * 1024 * 1024:
                raise RuntimeError('後端壓縮檔超過大小限制。')
            package = root / 'source.tar.gz'
            package.write_bytes(archive)
            with tarfile.open(package) as entries:
                for member in entries.getmembers():
                    parts = member.name.split('/', 1)
                    if len(parts) != 2 or not parts[1]:
                        continue
                    member.name = parts[1]
                    entries.extract(member, path=destination, filter='data')
        if not (destination / 'cli.lua').is_file():
            raise RuntimeError('後端壓縮檔缺少 CLI。')
        (destination / '.source-commit').write_text(COMMIT + '\n')
        if target.exists():
            raise RuntimeError('後端版本目錄不完整，已保留現有資料。')
        destination.rename(target)
    return target


if __name__ == '__main__':
    ensure_backend()
    print('Pinned VM backend ready.')
