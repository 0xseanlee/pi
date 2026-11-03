const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('app.js', 'utf8');
const identity = { service: 'pi-station', api_version: 1, device_id: 'sean', hostname: 'sean', login_required: true, tls_port: 8443 };
function browser({ response, stored = null, subnet = null, url = 'https://0xseanlee.github.io/pi/' } = {}) {
  const elements = new Map(), events = new Map(), timers = new Map(), calls = [], saved = [], navigation = [];
  let timerId = 0;
  function element(id) {
    if (!elements.has(id)) elements.set(id, { value: '', textContent: '', dataset: {}, hidden: false,
      disabled: false, href: '', listeners: new Map(),
      addEventListener(name, fn) { this.listeners.set(name, fn); } });
    return elements.get(id);
  }
  const location = new URL(url); location.assign = (value) => navigation.push(value);
  const context = { URL, AbortController, Set, Promise, location,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    localStorage: { getItem(k) { return k === 'pi-station-address' ? stored : k === 'pi-station-subnet' ? subnet : null; }, setItem(k, v) { saved.push({ k, v }); } },
    document: { hidden: false, querySelector: element, addEventListener: (n, fn) => events.set(n, fn) },
    window: { addEventListener: (n, fn) => events.set(n, fn), dispatchEvent: (e) => events.get(e.type)?.(e) },
    setTimeout(fn, delay) { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
    async fetch(address, options) {
      calls.push({ address, options });
      const path = new URL(address).pathname;
      const data = response ? await response(address, options) : path.endsWith('/discovery') ? identity : { authenticated: false };
      return { ok: true, status: 200, async json() { return data; } };
    },
  };
  vm.runInNewContext(source, context);
  return { element, context, calls, saved, navigation, events, timers };
}
const settle = () => new Promise(setImmediate);

test('GitHub page finds a Pi without navigating to its LAN page', async () => {
  const b = browser(); await settle();
  assert.equal(b.element('#status-text').textContent, '未登入');
  assert.equal(b.navigation.length, 0);
  assert.equal(b.element('#login-panel').hidden, false);
  assert.ok(b.calls.every(({ address }) => address.startsWith('https://')));
});

test('remote login uses a memory bearer token and omits third-party cookies', async () => {
  const b = browser({ response: (address) => {
    if (address.endsWith('/discovery')) return identity;
    if (address.endsWith('/login')) return { authenticated: true, username: 'sean', csrf: 'test-csrf', token: 'test-token' };
    return { authenticated: false };
  } }); await settle();
  b.element('#password').value = 'test-only-password';
  await b.element('#login-form').listeners.get('submit')({ preventDefault() {} });
  await b.context.window.piRequest('system');
  const request = b.calls.at(-1);
  assert.equal(request.options.credentials, 'omit');
  assert.equal(request.options.headers.Authorization, 'Bearer test-token');
  assert.equal(request.options.headers['X-CSRF-Token'], 'test-csrf');
  assert.equal(b.element('#password').value, '');
  assert.ok(!JSON.stringify(b.saved).includes('test-token'));
  assert.ok(!JSON.stringify(b.saved).includes('test-only-password'));
  assert.equal(b.navigation.length, 0);
});

test('manual entry rejects public endpoints and URL credentials', async () => {
  const b = browser(); await settle();
  for (const url of ['https://evil.example/', 'https://user:pass@10.0.0.1:8443/']) {
    b.element('#address').value = url;
    b.element('#address-form').listeners.get('submit')({ preventDefault() {} });
    assert.equal(b.element('#form-message').textContent, '請輸入樹莓派區網位址。');
  }
});

test('missing device keeps the browser on GitHub and offers certificate check', async () => {
  const b = browser({ response: () => { throw Error('offline'); } }); await settle();
  assert.equal(b.element('#status-text').textContent, '未連線');
  assert.equal(b.navigation.length, 0);
  assert.ok(b.element('#local-link').href.startsWith('https://'));
});

test('wrong service identity never displays the login form', async () => {
  const b = browser({ response: () => ({ ...identity, device_id: 'other' }) }); await settle();
  assert.equal(b.element('#login-panel').hidden, true);
  assert.equal(b.navigation.length, 0);
});

test('same-origin Pi page can still use its secure session cookie', async () => {
  const b = browser({ url: 'https://sean.local:8443/' }); await settle();
  const own = b.calls.find(({ address }) => address === 'https://sean.local:8443/api/v1/session');
  assert.equal(own.options.credentials, 'same-origin');
});


test('fresh browser does not assume a fixed school IP', async () => {
  const b = browser({ response: () => { throw Error('offline'); } }); await settle();
  assert.ok(!b.calls.some(({ address }) => address.includes('10.100.7.67')));
  assert.equal(b.element('#address').value, '');
});

test('hotspot scan finds sean after DHCP assigns a different IP', async () => {
  const b = browser({ response: (address) => {
    if (address.startsWith('https://172.20.10.11:8443/')) return identity;
    throw Error('offline');
  } }); await settle();
  assert.equal(b.element('#device-address').textContent, 'https://172.20.10.11:8443');
  assert.equal(b.navigation.length, 0);
});

test('Wi-Fi scan rediscovers changed IP and rejects a different hostname', async () => {
  const b = browser({ stored: 'https://10.100.7.67:8443', response: (address) => {
    if (address.startsWith('https://10.100.7.89:8443/')) return { ...identity, hostname: 'other' };
    if (address.startsWith('https://10.100.7.203:8443/')) return identity;
    throw Error('offline');
  } }); await settle();
  assert.equal(b.element('#device-address').textContent, 'https://10.100.7.203:8443');
  assert.ok(b.saved.some(({ k, v }) => k === 'pi-station-address' && v === 'https://10.100.7.203:8443'));
  assert.ok(b.calls.filter(({ address }) => address.endsWith('/discovery')).every(({ options }) => !options.headers.Authorization));
});

test('new Wi-Fi subnet can be searched without knowing the Pi IP', async () => {
  const b = browser({ response: (address) => {
    if (address.startsWith('https://192.168.42.77:8443/')) return identity;
    throw Error('offline');
  } }); await settle();
  b.element('#subnet').value = '192.168.42.52/24';
  b.element('#subnet-form').listeners.get('submit')({ preventDefault() {} });
  await settle();
  assert.equal(b.element('#device-address').textContent, 'https://192.168.42.77:8443');
  assert.equal(b.element('#subnet').value, '192.168.42.0/24');
});

test('subnet search rejects public networks and oversized ranges', async () => {
  const b = browser(); await settle();
  for (const value of ['8.8.8.0/24', '10.0.0.0/16', '127.0.0.0/24', '192.168.999.0/24']) {
    b.element('#subnet').value = value;
    b.element('#subnet-form').listeners.get('submit')({ preventDefault() {} });
    assert.ok(b.element('#subnet-message').textContent.includes('範圍限'));
  }
});


test('mDNS discovery learns the current Wi-Fi subnet instead of retaining an old network', async () => {
  const b = browser({ stored: 'https://172.20.10.6:8443', response: (address) => {
    if (address.startsWith('https://sean.local:8443/')) return { ...identity, address: '192.168.50.91' };
    if (address.endsWith('/session')) return { authenticated: false };
    throw Error('offline');
  } }); await settle();
  assert.equal(b.element('#subnet').value, '192.168.50.0/24');
  assert.ok(b.saved.some(({ k, v }) => k === 'pi-station-history' && v.includes('192.168.50.91')));
});
