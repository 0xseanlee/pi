(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const key = 'pi-station-address';
  const subnetKey = 'pi-station-subnet';
  const historyKey = 'pi-station-history';
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
  function subnet(value) {
    const [ip, mask, extra] = value.trim().split('/');
    const p = ip.split('.').map(Number), bits = Number(mask);
    if (extra || !/^\d+\.\d+\.\d+\.\d+$/.test(ip) || p.length !== 4 ||
        p.some((n) => !Number.isInteger(n) || n < 0 || n > 255) ||
        !Number.isInteger(bits) || bits < 24 || bits > 30 || !localHost(ip) || p[0] === 127) {
      throw new Error('請填區網網段，例如 192.168.1.0/24；範圍限 /24 至 /30。');
    }
    const size = 2 ** (32 - bits);
    const number = p.reduce((n, part) => n * 256 + part, 0);
    const base = Math.floor(number / size) * size;
    const address = (n) => [Math.floor(n / 16777216), Math.floor(n / 65536) % 256, Math.floor(n / 256) % 256, n % 256].join('.');
    return { cidr: `${address(base)}/${bits}`, addresses: Array.from({ length: size - 2 }, (_, n) => `https://${address(base + n + 1)}:8443`) };
  }
  function addressSubnet(value) {
    try {
      const host = new URL(value).hostname;
      if (!/^\d+\.\d+\.\d+\.\d+$/.test(host) || host.startsWith('127.')) return '';
      return subnet(host + (host.startsWith('172.20.10.') ? '/28' : '/24')).cidr;
    } catch { return ''; }
  }
  let saved = '', rememberedSubnet = '', history = [];
  try { const value = localStorage.getItem(key); if (value) saved = normalize(value); } catch { /* 可手動輸入 */ }
  try {
    const data = JSON.parse(localStorage.getItem(historyKey) || '[]');
    if (Array.isArray(data)) history = data.slice(0, 4).map(normalize);
  } catch { history = []; }
  try { const value = localStorage.getItem(subnetKey); if (value) rememberedSubnet = subnet(value).cidr; } catch { /* 忽略無效資料 */ }
  if (!rememberedSubnet) rememberedSubnet = addressSubnet(saved);
  $('#address').value = saved;
  $('#subnet').value = rememberedSubnet;

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
    const timer = setTimeout(() => controller.abort(), body ? 90000 : path === 'discovery' ? 2000 : 5000);
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
  async function scan(preferred, selectedSubnet) {
    stop(); const run = generation;
    endpoint = ''; locked();
    $('#login-panel').hidden = true;
    state('searching', '搜尋中');
    $('#device-address').textContent = '—';
    $('#discovery-message').textContent = '正在搜尋 sean';
    $('#discovery-detail').textContent = '';
    $('#scan-stop').hidden = false;
    const seen = new Set();
    let winner = '', winnerData = {};
    const deadline = Date.now() + 90000;
    async function group(addresses, label) {
      const queue = addresses.filter((address) => !seen.has(address));
      queue.forEach((address) => seen.add(address));
      let index = 0, completed = 0;
      async function worker() {
        while (!winner && run === generation && index < queue.length && Date.now() < deadline) {
          const address = queue[index++];
          try {
            const data = await request('discovery', undefined, address);
            if (data.service !== 'pi-station' || data.device_id !== 'sean' ||
                (data.hostname !== undefined && data.hostname !== 'sean') ||
                data.api_version !== 1 || data.login_required !== true || data.tls_port !== 8443) continue;
            if (!winner && run === generation) {
              winner = address; winnerData = data;
              for (const controller of controllers) controller.abort();
            }
          } catch { /* 無法連線、憑證或瀏覽器限制，繼續搜尋 */ }
          finally {
            completed++;
            if (run === generation && !winner) $('#discovery-detail').textContent = `${label} · ${completed}/${queue.length}`;
          }
        }
      }
      await Promise.all(Array.from({ length: Math.min(12, queue.length) }, worker));
    }
    await group([...new Set([preferred, own ? location.origin : '', 'https://sean.local:8443',
      'https://sean:8443', saved, ...history].filter(Boolean))], '名稱與最近位址');
    if (!winner && run === generation && !selectedSubnet) await group(subnet('172.20.10.0/28').addresses, '手機熱點');
    const networks = selectedSubnet ? [selectedSubnet] : [...new Set([rememberedSubnet,
      addressSubnet(saved), ...history.map(addressSubnet)].filter(Boolean))].slice(0, 2);
    for (const network of networks) {
      if (winner || run !== generation || Date.now() >= deadline) break;
      await group(subnet(network).addresses, network);
    }
    if (run !== generation) return;
    $('#scan-stop').hidden = true;
    if (!winner) {
      state('offline', '未連線');
      $('#device-note').textContent = '未連線';
      $('#service-status').textContent = '無法連線';
      $('#discovery-message').textContent = '尚未找到 sean';
      $('#discovery-detail').textContent = '確認搜尋網段、區網權限與憑證信任。';
      $('#local-link').href = preferred || saved || 'https://sean.local:8443/';
      if (!document.hidden) retry = setTimeout(() => scan(), 60000);
      return;
    }
    endpoint = saved = winner;
    let actualAddress = '';
    try { if (winnerData.address) actualAddress = normalize(`https://${winnerData.address}:8443`); } catch { /* 僅接受合法區網位址 */ }
    history = [...new Set([winner, actualAddress, ...history].filter(Boolean))].slice(0, 4);
    rememberedSubnet = selectedSubnet || addressSubnet(actualAddress) || addressSubnet(winner) || rememberedSubnet;
    try {
      localStorage.setItem(key, winner);
      localStorage.setItem(historyKey, JSON.stringify(history));
      if (rememberedSubnet) localStorage.setItem(subnetKey, rememberedSubnet);
    } catch { /* 不影響本次連線 */ }
    $('#address').value = winner;
    $('#subnet').value = rememberedSubnet;
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
  $('#scan-stop').addEventListener('click', () => {
    stop(); $('#scan-stop').hidden = true; state('offline', '已停止搜尋');
    $('#discovery-message').textContent = '已停止搜尋'; $('#discovery-detail').textContent = '';
  });
  $('#subnet-form').addEventListener('submit', (event) => {
    event.preventDefault();
    try {
      rememberedSubnet = subnet($('#subnet').value).cidr;
      $('#subnet').value = rememberedSubnet; $('#subnet-message').textContent = '';
      try { localStorage.setItem(subnetKey, rememberedSubnet); } catch { /* 本次仍可搜尋 */ }
      scan(undefined, rememberedSubnet);
    } catch (e) { $('#subnet-message').textContent = e.message; }
  });
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
  window.addEventListener('online', () => { if (endpoint) heartbeat(); else scan(); });
  window.addEventListener('pagehide', stop);
  scan();
})();
