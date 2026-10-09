const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app.js', 'utf8');
const identity = { service: 'pi-station', api_version: 1, hostname: 'sean' };

function browser({ ios = false, url = 'https://0xseanlee.me/pi/', response = () => identity } = {}) {
  const elements = new Map(), events = new Map(), timers = new Map(), calls = [], navigation = [];
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
    localStorage: { getItem() { return null; }, setItem() {} },
    document: { hidden: false, querySelector: element, addEventListener: (n, fn) => events.set(n, fn) },
    window: { addEventListener: (n, fn) => events.set(n, fn) },
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    async fetch(address, options) {
      calls.push(address);
      const data = await response(address, options);
      return { ok: true, async json() { return data; } };
    },
  };
  vm.runInNewContext(source, context);
  return { element, events, timers, calls, navigation, context };
}
const settle = () => new Promise(setImmediate);

test('finds the real identity automatically without any saved or entered address', async () => {
  const b = browser({ response: (url) => {
    if (url.startsWith('http://sean.local:8000/')) return identity;
    throw Error('unavailable');
  } });
  await settle();
  assert.equal(b.element('#address').value, '');
  assert.equal(b.element('#status-text').textContent, '已找到 Pi');
  assert.equal(b.element('#device-address').textContent, 'http://sean.local:8000');
});

test('searches the known iPhone hotspot range if Bonjour is unavailable', async () => {
  const b = browser({ response: (url) => {
    if (url.startsWith('http://172.20.10.6:8000/')) return identity;
    throw Error('unavailable');
  } });
  await settle();
  assert.equal(b.element('#device-address').textContent, 'http://172.20.10.6:8000');
});

test('rejects services that are not the expected Pi, and schedules a retry', async () => {
  const b = browser({ response: () => ({ ...identity, hostname: 'another-device' }) });
  await settle();
  assert.equal(b.element('#status-text').textContent, '尚未找到 Pi');
  assert([...b.timers.values()].some((timer) => timer.delay === 15000));
});

test('iPhone Safari automatically opens the local dashboard without blocked fetch requests', async () => {
  const b = browser({ ios: true });
  await settle();
  assert.equal(b.calls.length, 0);
  assert.equal(b.element('#status-text').textContent, '正在開啟本機控制台');
  const timer = [...b.timers.values()].find((t) => t.delay === 1500);
  timer.fn();
  assert.deepEqual(b.navigation, ['http://sean.local:8000/']);
});

test('Safari local dashboard checks its own identity without redirecting', async () => {
  const b = browser({ ios: true, url: 'http://sean.local:8000/' });
  await settle();
  assert.equal(b.element('#status-text').textContent, '已找到 Pi');
  assert.equal(b.calls[0], 'http://sean.local:8000/api/v1/identity');
  assert.deepEqual(b.navigation, []);
});

test('back navigation pauses the Safari handoff instead of trapping the back button', () => {
  const b = browser({ ios: true });
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
