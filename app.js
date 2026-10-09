(() => {
  'use strict';
  const storageKey = 'pi-station-address';
  const $ = (selector) => document.querySelector(selector);
  const input = $('#address');
  const display = $('#device-address');
  const message = $('#form-message');
  const status = $('#connection-status');
  const discovery = $('#discovery-message');
  const detail = $('#discovery-detail');
  const scanButton = $('#scan-button');
  const stayButton = $('#stay-button');
  let activeAddress = '', savedAddress = '', generation = 0;
  let retryTimer, handoffTimer;
  let pausedHandoff = false, csrf = '';
  const isLocalTLS = location.protocol === 'https:' && localHost(location.hostname);
  const controllers = new Set();

  function localHost(host) {
    if (host === 'localhost' || host === 'sean.local') return true;
    const parts = host.split('.').map(Number);
    if (parts.length !== 4 || parts.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return false;
    return parts[0] === 10 || parts[0] === 127 ||
      (parts[0] === 192 && parts[1] === 168) ||
      (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31);
  }

  function normalizeAddress(value) {
    const url = new URL(value.trim());
    if (!['http:', 'https:'].includes(url.protocol) || !localHost(url.hostname)) {
      throw new Error('請使用樹莓派的本機位址，例如 http://sean.local:8000。');
    }
    if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
      throw new Error('請只填入服務位址，不要包含帳密、路徑或查詢參數。');
    }
    return url.origin;
  }

  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) input.value = savedAddress = normalizeAddress(saved);
  } catch { /* 未提供儲存時仍能自動搜尋。 */ }

  function candidates() {
    const own = localHost(location.hostname) ? location.origin : '';
    if (isLocalTLS) return [own];
    const addresses = [own, savedAddress, 'http://sean.local:8000', 'http://192.168.68.63:8000'];
    // 這台 iPhone 熱點曾分配 172.20.10.6/28，只搜尋該小網段的服務。
    for (let n = 2; n <= 14; n++) addresses.push(`http://172.20.10.${n}:8000`);
    return [...new Set(addresses.filter(Boolean))];
  }

  function setState(state, text) {
    status.dataset.state = state;
    $('#status-text').textContent = text;
  }

  async function identify(address) {
    const controller = new AbortController();
    controllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch(`${address}/api/v1/discovery`, {
        signal: controller.signal, cache: 'no-store', credentials: 'omit', mode: 'cors',
        referrerPolicy: 'no-referrer', targetAddressSpace: 'local',
      });
      if (!response.ok) throw new Error('服務未回應');
      const device = await response.json();
      if (device.service !== 'pi-station' || device.api_version !== 1 || device.device_id !== 'sean' || device.login_required !== true || device.tls_port !== 8443) {
        throw new Error('不是 sean 的樹莓派服務');
      }
      return device;
    } finally {
      clearTimeout(timeout);
      controllers.delete(controller);
    }
  }

  function stop() {
    generation++;
    clearTimeout(retryTimer);
    clearTimeout(handoffTimer);
    for (const controller of controllers) controller.abort();
    controllers.clear();
  }

  function schedule(fn, delay) {
    clearTimeout(retryTimer);
    if (!document.hidden) retryTimer = setTimeout(fn, delay);
  }

  function locked(text = '') {
    csrf = '';
    $('#login-panel').hidden = !isLocalTLS;
    $('#account-panel').hidden = true;
    $('#service-status').textContent = '需要登入';
    $('#device-note').textContent = '已找到裝置，尚未登入';
    setState('locked', '需要登入');
    discovery.textContent = '找到 sean 了，請先登入。';
    detail.textContent = '使用樹莓派 sean 帳號的密碼。其他人即使打開這個網址，也需要登入。';
    if (text) $('#login-message').textContent = text;
  }

  function authenticated(data) {
    csrf = data.csrf;
    $('#login-panel').hidden = true;
    $('#account-panel').hidden = false;
    $('#device-note').textContent = '登入成功';
    $('#service-status').textContent = '已驗證 sean';
    setState('connected', '已登入 sean');
    discovery.textContent = '歡迎回來，sean。';
    detail.textContent = '登入有效期間最多 30 分鐘；離開共用裝置前請登出。控制功能等待你設定。';
    $('#login-message').textContent = '';
  }

  async function api(path, body) {
    if (!isLocalTLS) throw new Error('請在樹莓派 HTTPS 控制台登入。');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    controllers.add(controller);
    try {
      const response = await fetch(`/api/v1/${path}`, {
        method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
        signal: controller.signal,
        headers: body ? { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}) } : {},
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(response.status === 429 ? '嘗試次數過多，請等 60 秒再試。' :
          response.status === 401 ? '帳號或密碼不正確，或登入已過期。' : '無法完成操作，請重新整理後再試。');
      }
      return data;
    } finally {
      clearTimeout(timeout);
      controllers.delete(controller);
    }
  }

  async function refreshSession() {
    const data = await api('session');
    if (data.authenticated && data.username === 'sean' && typeof data.csrf === 'string') authenticated(data);
    else locked();
  }

  function secureAddress(address) {
    const url = new URL(address);
    return `https://${url.hostname}:8443`;
  }

  async function found(address) {
    activeAddress = savedAddress = address;
    try { localStorage.setItem(storageKey, address); } catch { /* 可繼續使用。 */ }
    display.textContent = address;
    $('#local-link').href = `${secureAddress(address)}/`;
    scanButton.disabled = false;
    if (!isLocalTLS || address !== location.origin) { handoff(secureAddress(address)); return; }
    locked();
    try { await refreshSession(); } catch { locked('暫時無法確認登入狀態，請重試。'); }
    schedule(heartbeat, 10000);
  }

  async function heartbeat() {
    const run = generation;
    try {
      await identify(activeAddress);
      if (run !== generation) return;
      if (isLocalTLS) await refreshSession();
      if (run === generation) schedule(heartbeat, 10000);
    } catch {
      if (run === generation) scan();
    }
  }

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const needsLocalPage = location.protocol === 'https:' && !localHost(location.hostname) &&
    isIOS && !('targetAddressSpace' in Request.prototype);

  function handoff(address = 'https://sean.local:8443') {
    stop();
    setState('handoff', '正在開啟本機控制台');
    display.textContent = '等待本機服務確認';
    $('#device-note').textContent = '前往樹莓派控制台';
    discovery.textContent = '正在開啟樹莓派上的控制台…';
    detail.textContent = '即將開啟 Pi 的 HTTPS 登入頁。首次使用請核對本機憑證；密碼只在這台 Pi 的頁面輸入。';
    $('#local-link').href = `${address}/`;
    stayButton.hidden = false;
    handoffTimer = setTimeout(() => location.assign(`${address}/`), 1500);
  }

  async function scan(preferred) {
    if (needsLocalPage || (localHost(location.hostname) && location.protocol !== 'https:')) { handoff(preferred ? secureAddress(preferred) : undefined); return; }
    stop();
    const run = generation;
    activeAddress = '';
    csrf = '';
    $('#login-panel').hidden = true;
    $('#account-panel').hidden = true;
    setState('searching', '正在搜尋');
    scanButton.disabled = true;
    display.textContent = '搜尋中';
    $('#device-note').textContent = '正在尋找你的裝置';
    $('#service-status').textContent = '等待回應';
    discovery.textContent = '正在自動搜尋 sean…';
    detail.textContent = '若瀏覽器詢問區域網路權限，請允許此網站尋找裝置。';
    const queue = preferred ? [preferred, ...candidates().filter((a) => a !== preferred)] : candidates();
    let winner = '', cursor = 0;
    async function worker() {
      while (cursor < queue.length && !winner && run === generation) {
        const address = queue[cursor++];
        try {
          await identify(address);
          if (!winner && run === generation) {
            winner = address;
            for (const controller of controllers) controller.abort();
          }
        } catch { /* 繼續搜尋下一個候選位址。 */ }
      }
    }
    await Promise.all(Array.from({ length: 4 }, worker));
    if (run !== generation) return;
    if (winner) { found(winner); return; }
    setState('offline', '尚未找到 Pi');
    display.textContent = '尚未找到';
    $('#device-note').textContent = '等待裝置連上相同網路';
    discovery.textContent = '還沒收到樹莓派的回應。';
    detail.textContent = '請確認熱點與 Pi 已開啟，並允許區域網路存取。15 秒後會再搜尋；若瀏覽器阻擋連線，可開啟樹莓派控制台。';
    scanButton.disabled = false;
    schedule(scan, 15000);
  }

  $('#login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const password = $('#password');
    const button = $('#login-button');
    if (!isLocalTLS || button.disabled) return;
    button.disabled = true;
    $('#login-message').textContent = '正在驗證…';
    try {
      const result = await api('login', { username: 'sean', password: password.value });
      authenticated(result);
    } catch (error) {
      locked(error.name === 'AbortError' ? '連線逾時，請重試。' : error.message);
    } finally {
      password.value = '';
      button.disabled = false;
    }
  });
  $('#logout-button').addEventListener('click', async () => {
    const button = $('#logout-button');
    button.disabled = true;
    try { await api('logout', {}); locked('已登出。'); }
    catch (error) { detail.textContent = `登出尚未確認：${error.message}`; }
    finally { button.disabled = false; }
  });
  scanButton.addEventListener('click', () => { pausedHandoff = false; scan(); });
  function pauseHandoff() {
    stop();
    pausedHandoff = true;
    stayButton.hidden = true;
    setState('offline', '等待開啟本機控制台');
    discovery.textContent = '已暫停自動前往。';
    detail.textContent = '這個 Safari 需要開啟樹莓派控制台才能確認連線。';
  }
  stayButton.addEventListener('click', pauseHandoff);
  $('#address-form').addEventListener('submit', (event) => {
    event.preventDefault();
    message.classList.remove('error');
    try {
      savedAddress = input.value = normalizeAddress(input.value);
      try { localStorage.setItem(storageKey, savedAddress); } catch { /* 此次仍可使用。 */ }
      message.textContent = '正在嘗試這個位址。';
      scan(savedAddress);
    } catch (error) {
      message.textContent = error instanceof TypeError ? '請輸入完整的本機服務位址。' : error.message;
      message.classList.add('error');
    }
  });
  window.addEventListener('online', () => { if (!pausedHandoff) scan(); });
  window.addEventListener('pagehide', stop);
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) { if (needsLocalPage) pauseHandoff(); else scan(); }
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop(); else if (!pausedHandoff) scan();
  });
  scan();
})();
