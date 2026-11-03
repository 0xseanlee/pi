(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  let csrf = '', ready = false, folder = '.', editing = '', dirty = false;
  let terminal = '', cursor = 0, polling = false, terminalTimer;
  const bytes = (n) => n >= 1073741824 ? `${(n / 1073741824).toFixed(1)} GiB` : `${(n / 1048576).toFixed(1)} MiB`;
  const quote = (s) => `'${s.replaceAll("'", "'\\''")}'`;
  const join = (name) => folder === '.' ? name : `${folder}/${name}`;

  function message(text, error = false) {
    $('#action-message').textContent = text;
    $('#action-message').classList.toggle('error', error);
  }
  async function api(action, body = {}) {
    if (!csrf) throw new Error('請先登入樹莓派');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const r = await fetch(`/api/v1/control/${action}`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify(body), signal: controller.signal,
      });
      const data = await r.json();
      if (!r.ok) {
        if (r.status === 401) lock();
        throw new Error(data.error || '操作失敗');
      }
      return data;
    } finally { clearTimeout(timer); }
  }
  function action(selector, fn) {
    $(selector).addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try { await fn(); } catch (e) { message(e.message, true); }
      finally { button.disabled = false; }
    });
  }
  function form(selector, fn) {
    $(selector).addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = event.currentTarget.querySelector('button[type="submit"]');
      button.disabled = true;
      try { await fn(); } catch (e) { message(e.message, true); }
      finally { button.disabled = false; }
    });
  }
  function tab(name) {
    document.querySelectorAll('[data-pane]').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    document.querySelectorAll('[data-tab]').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === name));
  }
  document.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', async () => {
    tab(b.dataset.tab);
    try {
      if (b.dataset.tab === 'files') await files();
      if (b.dataset.tab === 'overview') await overview();
      if (b.dataset.tab === 'jobs') await jobs();
      if (b.dataset.tab === 'network') await network();
    } catch (e) { message(e.message, true); }
  }));
  function lock() {
    csrf = ''; ready = false; terminal = ''; clearTimeout(terminalTimer);
    $('#workbench').hidden = true;
    document.body.classList.remove('logged-in');
  }
  window.addEventListener('pi-session', async ({ detail }) => {
    if (!detail) { lock(); return; }
    csrf = detail.csrf;
    $('#workbench').hidden = false;
    document.body.classList.add('logged-in');
    if (!ready) {
      ready = true;
      try { await overview(); } catch (e) { message(e.message, true); }
    }
  });
  async function overview() {
    const data = await api('system');
    const values = [['主機', data.hostname], ['CPU 平均負載', data.load.toFixed(2)],
      ['可用記憶體', `${bytes(data.memory_available)} / ${bytes(data.memory_total)}`],
      ['可用儲存空間', `${bytes(data.disk_available)} / ${bytes(data.disk_total)}`]];
    $('#metrics').replaceChildren(...values.map(([label, value]) => {
      const card = document.createElement('div'); card.className = 'metric';
      const title = document.createElement('span'); title.textContent = label;
      const text = document.createElement('strong'); text.textContent = value;
      card.append(title, text); return card;
    }));
  }
  action('#refresh-overview', overview);
  async function files() {
    const data = await api('files', { path: folder });
    folder = data.path;
    $('#current-path').textContent = folder === '.' ? '~' : `~/${folder}`;
    $('#file-list').replaceChildren(...data.entries.map((item) => {
      const row = document.createElement('div'); row.className = 'file-row';
      const open = document.createElement('button'); open.type = 'button';
      open.className = 'file-name'; open.textContent = `${item.directory ? '▸ ' : ''}${item.name}`;
      open.addEventListener('click', async () => {
        try {
          if (item.directory) { folder = item.path; await files(); }
          else { await edit(item.path); }
        } catch (e) { message(e.message, true); }
      });
      const size = document.createElement('span'); size.className = 'help';
      size.textContent = item.directory ? '資料夾' : `${item.size.toLocaleString()} B`;
      const rename = document.createElement('button'); rename.type = 'button';
      rename.className = 'secondary mini'; rename.textContent = '改名';
      rename.addEventListener('click', async () => {
        const name = prompt('新名稱', item.name);
        if (!name || name === item.name) return;
        try { await api('files', { op: 'rename', path: item.path, target: join(name) }); await files(); }
        catch (e) { message(e.message, true); }
      });
      row.append(open, size, rename);
      if (!item.directory) {
        const download = document.createElement('button'); download.type = 'button';
        download.className = 'secondary mini'; download.textContent = '下載';
        download.addEventListener('click', async () => {
          try {
            const data = await api('files', { op: 'download', path: item.path });
            const blob = new Blob([Uint8Array.from(atob(data.data), (c) => c.charCodeAt(0))]);
            const url = URL.createObjectURL(blob); const link = document.createElement('a');
            link.href = url; link.download = data.name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 10000);
          } catch (e) { message(e.message, true); }
        });
        row.append(download);
      }
      return row;
    }));
    if (!data.entries.length) $('#file-list').textContent = '這個資料夾目前沒有檔案。';
  }
  function discard() { return !dirty || confirm('有尚未儲存的修改，確定捨棄？'); }
  async function edit(path) {
    if (!discard()) return;
    const data = await api('files', { op: 'read', path });
    editing = data.path; dirty = false;
    $('#editor-path').value = data.path; $('#editor').value = data.text;
    $('#editor-panel').hidden = false;
    $('#editor-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  action('#files-refresh', files);
  action('#files-up', async () => { folder = folder.includes('/') ? folder.slice(0, folder.lastIndexOf('/')) : '.'; await files(); });
  action('#file-new', () => {
    if (!discard()) return;
    editing = ''; dirty = false;
    $('#editor-path').value = join('main.py'); $('#editor').value = '';
    $('#editor-panel').hidden = false; $('#editor-path').focus();
  });
  action('#folder-new', async () => {
    const name = prompt('資料夾名稱'); if (!name) return;
    await api('files', { op: 'mkdir', path: join(name) }); await files();
  });
  async function save() {
    const path = $('#editor-path').value.trim();
    await api('files', { op: 'write', path, text: $('#editor').value, overwrite: path === editing });
    editing = path; dirty = false; message('檔案已儲存。'); await files(); return path;
  }
  action('#file-save', save);
  action('#editor-close', () => { if (discard()) { $('#editor-panel').hidden = true; dirty = false; } });
  $('#editor').addEventListener('input', () => { dirty = true; });
  $('#editor-path').addEventListener('input', () => { dirty = true; });
  window.addEventListener('beforeunload', (event) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
  $('#file-upload').addEventListener('change', async (event) => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 8 * 1024 * 1024) throw new Error('單檔上限 8 MiB');
      message('正在上傳…');
      const data = await new Promise((resolve, reject) => {
        const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = () => reject(new Error('檔案讀取失敗')); reader.readAsDataURL(file);
      });
      await api('files', { op: 'upload', path: join(file.name), data }); await files(); message('上傳完成。');
    } catch (e) { message(e.message, true); }
    finally { event.target.value = ''; }
  });
  function appendOutput(text) {
    const output = $('#terminal-output');
    const clean = text.replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g, '').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '').replace(/\r/g, '');
    output.textContent = (output.textContent + clean).slice(-262144);
    output.scrollTop = output.scrollHeight;
  }
  async function poll() {
    if (!terminal || !csrf || polling) return;
    polling = true;
    const id = terminal;
    try {
      const data = await api('terminal', { op: 'poll', id, cursor });
      if (terminal !== id) return;
      appendOutput(data.output); cursor = data.cursor;
      if (data.exited) { appendOutput('\n[終端機已結束]\n'); await api('terminal', { op: 'close', id }); terminal = ''; }
    } catch (e) { message(e.message, true); terminal = ''; }
    finally {
      polling = false;
      if (terminal) terminalTimer = setTimeout(poll, document.hidden ? 5000 : 1000);
    }
  }
  async function openTerminal() {
    if (terminal) return;
    const data = await api('terminal', { op: 'open', cwd: folder });
    terminal = data.id; cursor = 0; $('#terminal-output').textContent = '';
    clearTimeout(terminalTimer); poll();
  }
  action('#terminal-open', openTerminal);
  form('#terminal-form', async () => {
    await openTerminal();
    await api('terminal', { op: 'input', id: terminal, data: $('#terminal-input').value + '\n' });
    $('#terminal-input').value = '';
  });
  action('#terminal-interrupt', async () => { if (terminal) await api('terminal', { op: 'input', id: terminal, data: '\x03' }); });
  action('#terminal-close', async () => {
    if (terminal) { await api('terminal', { op: 'close', id: terminal }); terminal = ''; clearTimeout(terminalTimer); appendOutput('\n[連線已關閉]\n'); }
  });
  action('#file-run', async () => {
    const suffix = $('#editor-path').value.split('.').pop().toLowerCase();
    const runner = { py: 'python3', sh: 'bash', js: 'node' }[suffix];
    if (!runner) throw new Error('這個檔案類型請使用 Terminal 編譯或執行');
    const path = await save(); tab('terminal'); await openTerminal();
    await api('terminal', { op: 'input', id: terminal, data: `cd ~ && ${runner} ${quote(path)}\n` });
  });
  async function jobs() {
    const data = await api('jobs');
    $('#job-list').replaceChildren(...data.jobs.map((job) => {
      const card = document.createElement('article'); card.className = 'job-card';
      const heading = document.createElement('h4'); heading.textContent = job.name;
      const meta = document.createElement('p'); meta.className = 'help';
      meta.textContent = `${job.state} · ${job.autostart ? '開機啟動' : '手動啟動'} · ~/${job.cwd}`;
      const command = document.createElement('pre'); command.className = 'data-output'; command.textContent = job.command;
      const buttons = document.createElement('div'); buttons.className = 'button-row';
      for (const [op, label] of [['start', '啟動'], ['stop', '停止'], ['restart', '重啟'], ['logs', '日誌']]) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = label;
        button.addEventListener('click', async () => {
          button.disabled = true;
          try {
            const result = await api('jobs', { op, id: job.id });
            if (op === 'logs') { $('#job-output').textContent = result.output || '尚無日誌'; $('#job-output').hidden = false; }
            else await jobs();
          } catch (e) { message(e.message, true); }
          finally { button.disabled = false; }
        }); buttons.append(button);
      }
      card.append(heading, meta, command, buttons); return card;
    }));
    if (!data.jobs.length) $('#job-list').textContent = '尚未建立背景任務。';
  }
  action('#jobs-refresh', jobs);
  form('#job-form', async () => {
    await api('jobs', { op: 'create', name: $('#job-name').value, command: $('#job-command').value,
      cwd: $('#job-cwd').value, autostart: $('#job-autostart').checked });
    await jobs(); message('背景任務已建立並啟動。');
  });
  async function network() {
    const data = await api('network');
    for (const key of ['current', 'saved', 'nearby']) $(`#network-${key}`).textContent = data[key];
  }
  action('#network-refresh', network);
  form('#priority-form', async () => {
    await api('network', { op: 'priority', uuid: $('#network-uuid').value.trim(), priority: Number($('#network-priority').value) });
    await network(); message('優先序已更新；目前連線不會被強制切換。');
  });
})();
