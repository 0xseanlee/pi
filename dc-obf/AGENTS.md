# DC OBF continuity

- Speak Traditional Chinese. Project root on Pi: `/home/sean/roblox-luau-vm`.
- User wants to protect their own executor-side Lua/Luau code against copying.
  Target executor name/version and real-script compatibility remain unknown.
- Exact interface: `dc obf --setup` asks only `token:` (hidden) and returns;
  `dc obf` opens an on-demand foreground bot; Discord `/obf` takes a `.lua`
  attachment in `file`, updates a progress embed, returns protected.lua and exits
  after one eligible job. Ctrl+C cancels. No daemon or autostart.
- `--update` pulls public `0xseanlee/pi` main, package subdirectory `dc-obf/`.
  Preserve all other repo files. GitHub connector account is 0xseanlee; push/admin
  permissions verified and a real branch update succeeded. Pi needs no PAT to pull.
- Stable `/usr/local/bin/dc` symlinks to `/home/sean/dc-tools/bin/dc`.
  That file is the stable Python launcher, not a pip-generated entry point now.
  It selects ~/.local/share/dc-obf/current/venv/bin/python or the bootstrap
  ~/dc-tools/bin/python, and executes `-m dc_obf.cli` from home directory.
  Do not overwrite the stable launcher by reinstalling into the bootstrap venv.
- Updates build separate commit-named releases, install/test them, then atomically
  switch current; previous is retained. Incomplete releases are never activated.
  Bot run / update locks prevent concurrent changes. Token stays outside releases.
- Token config: ~/.config/dc/obf.json (0600), directory 0700. Setup validates app
  identity and automatically selects its owner ID. Never ask for token in chat.
  A failed setup attempt retains a private .token draft for Enter-to-retry.
- First runnable backend is pinned Prometheus Medium, LuaU target; it is NOT our
  own VM and has basic Luau support. Keep exact attribution in README and embeds:
  Based on Prometheus by Elias Oelschner, https://github.com/prometheus-lua/Prometheus
- Vendor commit a98c50165f2a53f6d765a82eee60dfea53803445 is isolated under
  ~/.local/lib/dc-obf/backends/prometheus-<commit>, with upstream LICENSE.
  Source gets parsed/transformed, never directly executed for bot jobs.
- Embed shows real stages and elapsed time, no invented percentage. Private
  server is user's chosen context; progress/result are regular channel replies.
- 15 tests passed on Pi, including original/VM-output equality for our own closure,
  vararg and nil-return fixture. A real GitHub-to-Pi update also passed those tests.
  No genuine Discord token has been entered by the assistant. Real Discord login,
  registration, upload/result delivery and executor compatibility remain untested.
- User asked to power off after preparation and will unplug Pi overnight. After
  shutdown, do not assume SSH is available; user will power on and run --update.
- Latest: user is AWAY FROM HOME with the Pi. Do not try the home IP or scan
  the home LAN to reach it. Changes can be tested locally and published to GitHub;
  user runs commands themselves. Their update reported repeated PyPI TLS EOF /
  remote disconnect warnings, before activating the candidate release.
- Advised user to Ctrl+C the repeatedly failing update and use the already
  installed bot (`dc obf --setup`, `dc obf`). Do not disable SSL verification.
- Dependency updater now prepares a platform/requirements-specific wheel cache,
  verifies SHA256, then builds and installs with --no-index. TLS, cert/proxy
  settings remain enabled. Cache is incomplete until download fully succeeds.
  Current OLD updater still needs to finish one online install to acquire this
  enhancement; don't promise it magically fixes the user's active TLS failures.
- This change was tested on Mac: 19 tests pass, 1 pinned-Lua fixture skipped;
  real fresh-cache and blocked-network cached installs both succeeded, with
  bot module imports and pip check passing. No Pi validation possible while away.

## Validation

```sh
~/dc-tools/bin/python -m unittest discover -s tests -v
dc obf --help
dc obf --update
```

No background automation or continued work was scheduled. Only resume work when
the user sends a new instruction; do not imply overnight changes will appear.
