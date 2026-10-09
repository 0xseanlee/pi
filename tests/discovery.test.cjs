const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app.js', 'utf8');
const identity = { service: 'pi-station', api_version: 1, device_id: 'sean', login_required: true, tls_port: 8443 };

function browser({ ios = false, url = 'https://sean.local:8443/', response = () => identity } = {}) {
  const elements = new Map(), events = new Map(), timers = new Map(), calls = [], navigation = [], saved = [];
  let timerId = 0;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', textContent: '', dataset: {}, hidden: false, disabled: false, href: '',
      classList: { add() {}, remove() {} }, listeners: new Map(),
      addEventListener(name, fn) { this.listeners.set(name, fn); },
    });
    return elements.get(id);
  }
  function Request() {}
  if (!ios) Request.prototype.targetAddressSpace = 'unknown';
  const location = new URL(url);
  location.assign = (value) => navigation.push(value);
  const context = {
    URL, Request, AbortController, Set, Promise,
    location,
    navigator: { userAgent: ios ? 'iPhone Safari' : 'Chrome', platform: '', maxTouchPoints: 0 },
    localStorage: { getItem() { return null; }, setItem(key, value) { saved.push({ key, value }); } },
    document: { hidden: false, querySelector: element, addEventListener: (n, fn) => events.set(n, fn) },
    window: { addEventListener: (n, fn) => events.set(n, fn) },
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    async fetch(address, options) {
      calls.push(address);
      const data = address === '/api/v1/session' ? { authenticated: false } : await response(address, options);
      return { ok: true, async json() { return data; } };
    },
  };
  vm.runInNewContext(source, context);
  return { element, events, timers, calls, navigation, saved, context };
}
const settle = () => new Promise(setImmediate);

test('finds the real identity automatically without any saved or entered address', async () => {
  const b = browser({ response: (url) => {
    if (url.startsWith('https://sean.local:8443/')) return identity;
    throw Error('unavailable');
  } });
  await settle();
  assert.equal(b.element('#address').value, '');
  assert.equal(b.element('#status-text').textContent, '需要登入');
  assert.equal(b.element('#device-address').textContent, 'https://sean.local:8443');
});

test('searches the known iPhone hotspot range if Bonjour is unavailable', async () => {
  const b = browser({ url: 'https://0xseanlee.me/pi/', response: (url) => {
    if (url.startsWith('http://172.20.10.6:8000/')) return identity;
    throw Error('unavailable');
  } });
  await settle();
  assert.equal(b.element('#local-link').href, 'https://172.20.10.6:8443/');
  [...b.timers.values()].find(t => t.delay === 1500).fn();
  assert.deepEqual(b.navigation, ['https://172.20.10.6:8443/']);
});

test('rejects services that are not the expected Pi, and schedules a retry', async () => {
  const b = browser({ response: () => ({ ...identity, device_id: 'another-device' }) });
  await settle();
  assert.equal(b.element('#status-text').textContent, '尚未找到 Pi');
  assert([...b.timers.values()].some((timer) => timer.delay === 15000));
});

test('iPhone Safari automatically opens the local dashboard without blocked fetch requests', async () => {
  const b = browser({ ios: true, url: 'https://0xseanlee.me/pi/' });
  await settle();
  assert.equal(b.calls.length, 0);
  assert.equal(b.element('#status-text').textContent, '正在開啟本機控制台');
  const timer = [...b.timers.values()].find((t) => t.delay === 1500);
  timer.fn();
  assert.deepEqual(b.navigation, ['https://sean.local:8443/']);
});

test('Safari local dashboard checks its own identity without redirecting', async () => {
  const b = browser({ ios: true, url: 'https://sean.local:8443/' });
  await settle();
  assert.equal(b.element('#status-text').textContent, '需要登入');
  assert.equal(b.calls[0], 'https://sean.local:8443/api/v1/discovery');
  assert.deepEqual(b.navigation, []);
});

test('back navigation pauses the Safari handoff instead of trapping the back button', () => {
  const b = browser({ ios: true, url: 'https://0xseanlee.me/pi/' });
  b.events.get('pageshow')({ persisted: true });
  b.events.get('visibilitychange')();
  assert(![...b.timers.values()].some((t) => t.delay === 1500));
  assert.equal(b.element('#discovery-message').textContent, '已暫停自動前往。');
});

test('manual entry cannot cause requests to arbitrary public sites', async () => {
  const b = browser();
  await settle();
  const before = b.calls.length;
  b.element('#address').value = 'https://untrusted.example';
  b.element('#address-form').listeners.get('submit')({ preventDefault() {} });
  await settle();
  assert.equal(b.calls.length, before);
  assert(b.element('#form-message').textContent.includes('本機位址'));
});


test('HTTP local pages only hand off to TLS and never request a session or accept a password', async () => {
  const b = browser({ url: 'http://sean.local:8000/' });
  await settle();
  assert.equal(b.calls.length, 0);
  b.element('#password').value = 'test-only';
  await b.element('#login-form').listeners.get('submit')({ preventDefault() {} });
  assert.equal(b.calls.length, 0);
  [...b.timers.values()].find(t => t.delay === 1500).fn();
  assert.deepEqual(b.navigation, ['https://sean.local:8443/']);
});

test('login submits only to the local TLS API, clears the input and keeps secrets out of storage', async () => {
  let request;
  const b = browser({ response: (url, options) => {
    if (url === '/api/v1/login') { request = options; return { authenticated: true, username: 'sean', csrf: 'test-csrf' }; }
    return identity;
  } });
  await settle();
  b.element('#password').value = 'test-only-password';
  await b.element('#login-form').listeners.get('submit')({ preventDefault() {} });
  assert.equal(request.credentials, 'same-origin');
  assert.deepEqual(JSON.parse(request.body), { username: 'sean', password: 'test-only-password' });
  assert.equal(b.element('#password').value, '');
  assert(!JSON.stringify(b.saved).includes('test-only-password'));
  assert.equal(b.element('#login-panel').hidden, true);
  assert.equal(b.element('#status-text').textContent, '已登入 sean');
});
