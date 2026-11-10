#!/usr/bin/env python3
"""Stable launcher: select only a fully tested active release, else bootstrap."""
import os
from pathlib import Path
import sys

root = Path.home() / '.local/share/dc-obf/current'
python = root / 'venv/bin/python'
if not (root / '.ready').is_file() or not python.is_file():
    python = Path.home() / 'dc-tools/bin/python'
environment = os.environ.copy()
environment.pop('PYTHONPATH', None)
os.execve(str(python), [str(python), '-m', 'dc_obf.cli', *sys.argv[1:]], environment)
