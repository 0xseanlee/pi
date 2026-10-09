#!/usr/bin/env python3
"""Prefer the configured Wi-Fi hotspot without interrupting absent-hotspot use.

Configuration and passwords live on the Raspberry Pi, outside this repository.
NetworkManager handles fallback when the hotspot disappears.
"""
import json
import logging
import os
from pathlib import Path
import subprocess
import time

CONFIG = Path('/etc/pi-station-wifi.json')
STATE = Path('/run/pi-station-wifi/state.json')


def nm(*args, timeout=40):
    return subprocess.run(
        ['/usr/bin/nmcli', '--colors', 'no', *args],
        capture_output=True, text=True, check=True, timeout=timeout,
        env={**os.environ, 'LC_ALL': 'C'},
    ).stdout.strip()


def prefer(config, state, now):
    interface, target = config['interface'], config['uuid']
    if nm('radio', 'wifi') != 'enabled':
        return state
    current = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', interface)
    if current == target:
        return {}
    if now < state.get('retry_after', 0):
        return state
    visible = nm('-t', '--escape', 'no', '-f', 'SSID', 'device', 'wifi',
                 'list', 'ifname', interface, '--rescan', 'yes', timeout=25)
    if config['ssid'] not in visible.splitlines():
        return state
    logging.info('Preferred hotspot detected; activating on %s', interface)
    try:
        nm('--wait', '25', 'connection', 'up', 'uuid', target, 'ifname', interface)
    except (subprocess.SubprocessError, OSError):
        logging.warning('Hotspot activation failed; restoring a saved network')
        try:
            if current and current != '--':
                nm('--wait', '25', 'connection', 'up', 'uuid', current,
                   'ifname', interface)
            else:
                nm('--wait', '25', 'device', 'connect', interface)
        except (subprocess.SubprocessError, OSError):
            logging.warning('Immediate fallback failed; NetworkManager will retry')
        return {'retry_after': now + 180}
    logging.info('Connected to preferred hotspot')
    return {}


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    config = json.loads(CONFIG.read_text())
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    try:
        state = prefer(config, state, time.monotonic())
    except (subprocess.SubprocessError, OSError):
        logging.warning('Wi-Fi check unavailable; leaving the connection unchanged')
        return
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(STATE)


if __name__ == '__main__':
    main()
