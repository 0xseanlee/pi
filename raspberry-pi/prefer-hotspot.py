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


def recently_seen(interface, ssid):
    visible = nm('-t', '--escape', 'no', '-f', 'SSID,DBUS-PATH', 'device',
                 'wifi', 'list', 'ifname', interface, '--rescan', 'yes', timeout=25)
    for row in visible.splitlines():
        name, separator, path = row.rpartition(':')
        if not separator or name != ssid:
            continue
        result = subprocess.run(
            ['/usr/bin/busctl', 'get-property', 'org.freedesktop.NetworkManager',
             path, 'org.freedesktop.NetworkManager.AccessPoint', 'LastSeen'],
            capture_output=True, text=True, check=True, timeout=10,
        )
        last_seen = int(result.stdout.split()[1])
        age = time.clock_gettime(time.CLOCK_BOOTTIME) - last_seen
        if last_seen >= 0 and 0 <= age <= 15:
            return True
    return False


def prefer(config, state, now):
    interface, target = config['interface'], config['uuid']
    if nm('radio', 'wifi') != 'enabled':
        return state
    current = nm('-g', 'GENERAL.CON-UUID', 'device', 'show', interface)
    if current == target:
        return state
    if current and current != '--':
        state = {**state, 'fallback_uuid': current}
    if now < state.get('retry_after', 0):
        return state
    if not recently_seen(interface, config['ssid']):
        return state
    logging.info('Preferred hotspot detected; activating on %s', interface)
    try:
        nm('--wait', '25', 'connection', 'up', 'uuid', target, 'ifname', interface)
    except (subprocess.SubprocessError, OSError):
        logging.warning('Hotspot activation failed; restoring a saved network')
        try:
            fallback = state.get('fallback_uuid')
            if fallback and fallback != target:
                nm('--wait', '25', 'connection', 'up', 'uuid', fallback,
                   'ifname', interface)
            else:
                nm('--wait', '25', 'device', 'connect', interface)
        except (subprocess.SubprocessError, OSError):
            logging.warning('Immediate fallback failed; NetworkManager will retry')
        return {**state, 'retry_after': now + 180}
    logging.info('Connected to preferred hotspot')
    return {key: value for key, value in state.items() if key != 'retry_after'}


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    config = json.loads(CONFIG.read_text())
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {}
    try:
        state = prefer(config, state, time.monotonic())
    except (subprocess.SubprocessError, OSError, ValueError, IndexError):
        logging.warning('Wi-Fi check unavailable; leaving the connection unchanged')
        return
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.replace(STATE)


if __name__ == '__main__':
    main()
