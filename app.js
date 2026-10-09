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
  let pausedHandoff = false;
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
      const response = await fetch(`${address}/api/v1/identity`, {
        signal: controller.signal, cache: 'no-store', credentials: 'omit', mode: 'cors',
        referrerPolicy: 'no-referrer', targetAddressSpace: 'local',
      });
      if (!response.ok) throw new Error('服務未回應');
      const device = await response.json();
      if (device.service !== 'pi-station' || device.api_version !== 1 || device.hostname !== 'sean') {
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

  function found(address) {
    activeAddress = savedAddress = address;
    try { localStorage.setItem(storageKey, address); } catch { /* 可繼續使用。 */ }
    display.textContent = address;
    $('#device-note').textContent = '裝置正在回應';
    $('#service-status').textContent = '已回應';
    setState('connected', '已找到 Pi');
    discovery.textContent = '找到 sean 了。';
    detail.textContent = '會定期確認裝置是否仍在線。控制功能等待設定。';
    $('#local-link').href = `${address}/`;
    scanButton.disabled = false;
    schedule(heartbeat, 10000);
  }

  async function heartbeat() {
    const run = generation;
    try {
      await identify(activeAddress);
      if (run === generation) schedule(heartbeat, 10000);
    } catch {
      if (run === generation) scan();
    }
  }

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const needsLocalPage = location.protocol === 'https:' && !localHost(location.hostname) &&
    isIOS && !('targetAddressSpace' in Request.prototype);

  function handoff(address = 'http://sean.local:8000') {
    stop();
    setState('handoff', '正在開啟本機控制台');
    display.textContent = '等待本機服務確認';
    $('#device-note').textContent = '前往樹莓派控制台';
    discovery.textContent = '正在開啟樹莓派上的控制台…';
    detail.textContent = 'Safari 需要在樹莓派上確認連線。不用輸入 IP；請保持手機熱點開啟。';
    $('#local-link').href = `${address}/`;
    stayButton.hidden = false;
    handoffTimer = setTimeout(() => location.assign(`${address}/`), 1500);
  }

  async function scan(preferred) {
    if (needsLocalPage) { handoff(preferred); return; }
    stop();
    const run = generation;
    activeAddress = '';
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
