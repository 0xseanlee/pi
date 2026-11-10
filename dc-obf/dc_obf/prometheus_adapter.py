"""Pinned Prometheus VM backend (basic Luau support; target scripts need tests)."""
from pathlib import Path
import shutil
import subprocess
import sys
from .bootstrap_backend import COMMIT, vendor_path


def main():
    if len(sys.argv) != 3:
        return 2
    vendor = vendor_path()
    runtime = shutil.which('lua5.1') or shutil.which('luajit')
    if not runtime or not (vendor / 'cli.lua').is_file():
        return 3
    if not (vendor / '.source-commit').is_file() or (vendor / '.source-commit').read_text().strip() != COMMIT:
        return 3
    source, output = (str(Path(arg).resolve()) for arg in sys.argv[1:])
    # Compile and transform only. Never execute the submitted script.
    result = subprocess.run([
        runtime, str(vendor / 'cli.lua'), '--preset', 'Medium', '--LuaU', '--nocolors',
        '--out', output, source,
    ], cwd=vendor, stdin=subprocess.DEVNULL)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
