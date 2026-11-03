(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const key = 'pi-station-address';
  const localHost = (host) => {
    if (['sean.local', 'sean', 'localhost'].includes(host)) return true;
    const p = host.split('.').map(Number);
    return p.length === 4 && p.every((n) => Number.isInteger(n) && n >= 0 && n <= 255) &&
      (p[0] === 10 || p[0] === 127 || (p[0] === 192 && p[1] === 168) ||
       (p[0] === 172 && p[1] >= 16 && p[1] <= 31));
  };
  let endpoint = '', bearer = '', csrf = '', generation = 0, retry;
  const own = location.protocol === 'https:' && localHost(location.hostname);
  const controllers = new Set();
  function normalize(value) {
    const url = new URL(value.includes('://') ? value.trim() : `https://${value.trim()}:8443`);
    if (!localHost(url.hostname) || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
      throw new Error('請輸入樹莓派區網位址。');
    }
    url.protocol = 'https:';
    if (!url.port || url.port === '8000') url.port = '8443';
    return url.origin;
  }
  let saved = '';
  try { saved = normalize(localStorage.getItem(key) || 'https://10.100.7.67:8443'); } catch { /* 可手動輸入 */ }
  $('#address').value = saved;
  function state(value, text) {
    $('#connection-status').dataset.state = value;
    $('#status-text').textContent = text;
  }
  function locked(text = '') {
    bearer = ''; csrf = '';
    window.dispatchEvent(new CustomEvent('pi-session', { detail: null }));
    $('#login-panel').hidden = !endpoint;
    $('#account-panel').hidden = true;
    $('#controls-message').textContent = '請先登入';
    $('#controls-state').textContent = '未登入';
    $('#service-status').textContent = '未登入';
    $('#device-note').textContent = '已連線';
    $('#discovery-message').textContent = '已連線';
    $('#discovery-detail').textContent = '';
    $('#login-message').textContent = text;
    state('locked', '未登入');
  }
  function authenticated(data) {
    csrf = data.csrf;
    if (data.token) bearer = data.token;
    $('#login-panel').hidden = true;
    $('#account-panel').hidden = false;
    $('#controls-message').textContent = '';
    $('#controls-state').textContent = '已登入';
    $('#service-status').textContent = '已登入';
    $('#device-note').textContent = '已連線';
    $('#login-message').textContent = '';
    $('#discovery-message').textContent = '已連線';
    $('#discovery-detail').textContent = '';
    state('connected', '已連線');
    window.dispatchEvent(new CustomEvent('pi-session', { detail: data }));
  }
  async function request(path, body, address = endpoint) {
    if (!address) throw new Error('尚未連接裝置');
    const controller = new AbortController(); controllers.add(controller);
    const timer = setTimeout(() => controller.abort(), body ? 90000 : 5000);
    try {
      const response = await fetch(`${address}/api/v1/${path}`, {
        method: body ? 'POST' : 'GET', mode: 'cors', cache: 'no-store',
        credentials: address === location.origin ? 'same-origin' : 'omit',
        referrerPolicy: 'no-referrer', signal: controller.signal, targetAddressSpace: 'local',
        headers: { ...(body ? { 'Content-Type': 'application/json' } : {}),
          ...(address === endpoint && bearer ? { Authorization: `Bearer ${bearer}` } : {}),
          ...(body && csrf ? { 'X-CSRF-Token': csrf } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 401 && path !== 'login') locked('登入已過期');
        throw new Error(response.status === 429 ? '請稍候 60 秒再試' :
          data.error === 'invalid_credentials' ? '帳號或密碼不正確' : data.error || '操作失敗');
      }
      return data;
    } finally { clearTimeout(timer); controllers.delete(controller); }
  }
  window.piRequest = (action, body = {}) => request(`control/${action}`, body);
  function stop() {
    generation++; clearTimeout(retry);
    for (const controller of controllers) controller.abort();
    controllers.clear();
  }
  async function scan(preferred) {
    stop(); const run = generation;
    endpoint = ''; locked();
    $('#login-panel').hidden = true;
    state('searching', '連線中');
    $('#device-address').textContent = '—';
    $('#discovery-message').textContent = '正在尋找裝置';
    $('#discovery-detail').textContent = '';
    $('#scan-button').disabled = true;
    const queue = [...new Set([preferred, own ? location.origin : '', saved,
      'https://sean.local:8443', ...Array.from({ length: 13 }, (_, n) => `https://172.20.10.${n + 2}:8443`)].filter(Boolean))];
    let winner = '', index = 0;
    async function worker() {
      while (!winner && run === generation && index < queue.length) {
        const address = queue[index++];
        try {
          const data = await request('discovery', undefined, address);
          if (data.service !== 'pi-station' || data.device_id !== 'sean' || data.api_version !== 1 || data.login_required !== true || data.tls_port !== 8443) continue;
          if (!winner && run === generation) winner = address;
        } catch { /* 嘗試下一個位址 */ }
      }
    }
    await Promise.all(Array.from({ length: 4 }, worker));
    if (run !== generation) return;
    $('#scan-button').disabled = false;
    if (!winner) {
      state('offline', '未連線');
      $('#device-note').textContent = '未連線';
      $('#service-status').textContent = '無法連線';
      $('#discovery-message').textContent = '找不到裝置';
      $('#discovery-detail').textContent = '確認同一網路、裝置位址與憑證信任。';
      $('#local-link').href = preferred || saved || 'https://sean.local:8443/';
      if (!document.hidden) retry = setTimeout(() => scan(), 15000);
      return;
    }
    endpoint = saved = winner;
    try { localStorage.setItem(key, winner); } catch { /* 不影響本次連線 */ }
    $('#address').value = winner;
    $('#device-address').textContent = winner;
    $('#local-link').href = winner + '/';
    locked();
    try {
      const data = await request('session');
      if (data.authenticated) authenticated(data);
    } catch { /* 登入表單仍可操作 */ }
    if (!document.hidden) retry = setTimeout(heartbeat, 15000);
  }
  async function heartbeat() {
    if (!endpoint) return;
    try {
      const data = await request('session');
      if (data.authenticated) authenticated(data);
      else if (csrf) locked('登入已過期');
      if (!document.hidden) retry = setTimeout(heartbeat, 15000);
    } catch {
      stop(); endpoint = ''; locked('連線中斷');
      state('offline', '未連線');
      if (!document.hidden) retry = setTimeout(() => scan(), 15000);
    }
  }
  $('#login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    $('#login-button').disabled = true;
    $('#login-message').textContent = '登入中';
    try { authenticated(await request('login', { username: 'sean', password: $('#password').value })); }
    catch (error) { locked(error.name === 'AbortError' ? '連線逾時' : error.message); }
    finally { $('#password').value = ''; $('#login-button').disabled = false; }
  });
  $('#logout-button').addEventListener('click', async () => {
    try { await request('logout', {}); locked(); }
    catch (e) { $('#discovery-detail').textContent = e.message; }
  });
  $('#scan-button').addEventListener('click', () => scan());
  $('#stay-button').hidden = true;
  $('#address-form').addEventListener('submit', (event) => {
    event.preventDefault();
    try {
      saved = normalize($('#address').value);
      $('#form-message').textContent = '';
      $('#local-link').href = saved + '/';
      scan(saved);
    } catch (e) { $('#form-message').textContent = e.message; }
  });
  document.addEventListener('visibilitychange', () => {
    clearTimeout(retry);
    if (!document.hidden) { if (endpoint) heartbeat(); else scan(); }
  });
  window.addEventListener('online', () => { if (!endpoint) scan(); });
  window.addEventListener('pagehide', stop);
  scan();
})();
