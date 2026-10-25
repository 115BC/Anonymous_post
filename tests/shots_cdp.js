/* Headless Chrome screenshot harness over the DevTools protocol.
   Usage: node tests/shots_cdp.js [name ...]
   Requires the demo server on 127.0.0.1:5000 and tests/shot-seed.json. */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const BASE = process.cwd();
const SHOTS_DIR = path.join(BASE, 'tests', 'screens');
const SEED = JSON.parse(fs.readFileSync(path.join(BASE, 'tests', 'shot-seed.json'), 'utf8'));
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9333;
const HOST = '127.0.0.1';
const SITE = process.env.SHOT_SITE || `http://${HOST}:5000`;

fs.mkdirSync(SHOTS_DIR, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function httpJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => {
        try { resolve(JSON.parse(d)); } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

function httpPutJson(url) {
  return new Promise((resolve, reject) => {
    const req = http.request(url, { method: 'PUT' }, (res) => {
      let d = '';
      res.on('data', (c) => (d += c));
      res.on('end', () => {
        try { resolve(JSON.parse(d)); } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

const shots = [
  { name: 'login-light', url: '/login', w: 390, h: 844, scheme: 'light' },
  { name: 'login-dark', url: '/login', w: 390, h: 844, scheme: 'dark' },
  { name: 'register', url: '/register', w: 390, h: 844, scheme: 'light' },
  { name: 'home-light', url: '/', w: 390, h: 844, who: 'student', scheme: 'light' },
  { name: 'home-dark', url: '/', w: 390, h: 844, who: 'student', scheme: 'dark' },
  { name: 'home-320', url: '/', w: 320, h: 720, who: 'student', scheme: 'light', full: true },
  { name: 'home-desktop', url: '/', w: 1280, h: 900, who: 'student', scheme: 'light' },
  { name: 'notices-desktop', url: '/notices', w: 1280, h: 900, who: 'student', scheme: 'light' },
  { name: 'login-desktop', url: '/login', w: 1280, h: 800, scheme: 'light' },
  { name: 'feedback-desktop', url: '/feedback', w: 1280, h: 900, who: 'student', scheme: 'light' },
  { name: 'tree-desktop', url: '/tree', w: 1280, h: 900, who: 'student', scheme: 'light' },
  { name: 'tree-inbox-desktop', url: '/tree/inbox', w: 1280, h: 900, who: 'counselor', scheme: 'light' },
  { name: 'admin-desktop', url: '/admin/feedback', w: 1280, h: 900, who: 'admin', scheme: 'light' },
  { name: 'notices-light', url: '/notices', w: 390, h: 844, who: 'student', scheme: 'light' },
  { name: 'notices-dark', url: '/notices', w: 390, h: 844, who: 'student', scheme: 'dark' },
  { name: 'notice-view', url: '/notice/2', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'feedback', url: '/feedback', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'feedback-thread', url: `/feedback/t/${SEED.feedback_token}`, w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'tree', url: '/tree', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'tree-thread', url: `/tree/t/${SEED.tree_token}`, w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'tree-inbox', url: '/tree/inbox', w: 390, h: 844, who: 'counselor', scheme: 'light' },
  { name: 'tree-inbox-thread', url: '/tree/inbox/1', w: 390, h: 844, who: 'counselor', scheme: 'light', full: true },
  { name: 'admin-notices', url: '/admin/notices', w: 390, h: 844, who: 'admin', scheme: 'light' },
  { name: 'admin-notice-form', url: '/admin/notices/new', w: 390, h: 844, who: 'admin', scheme: 'light', full: true },
  { name: 'admin-feedback', url: '/admin/feedback', w: 390, h: 844, who: 'admin', scheme: 'light' },
  { name: 'admin-feedback-thread', url: '/admin/feedback/1', w: 390, h: 844, who: 'admin', scheme: 'light', full: true },
  { name: 'admin-users', url: '/admin/users', w: 390, h: 844, who: 'admin', scheme: 'light', full: true },
  { name: 'qa', url: '/qa', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'qa-new', url: '/qa/new', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'qa-thread', url: '/qa/1', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'resources', url: '/resources', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'resource-upload', url: '/resources/upload', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'admin-resources', url: '/admin/resources', w: 390, h: 844, who: 'admin', scheme: 'light', full: true },
  { name: 'qa-desktop', url: '/qa', w: 1280, h: 900, who: 'student', scheme: 'light' },
  { name: 'resources-desktop', url: '/resources', w: 1280, h: 900, who: 'student', scheme: 'light' },
  { name: 'account', url: '/account', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'privacy', url: '/privacy', w: 390, h: 844, who: 'student', scheme: 'light', full: true },
  { name: 'error-404', url: '/nope', w: 390, h: 844, who: 'student', scheme: 'light' },
];

const only = process.argv.slice(2);
const queue = only.length ? shots.filter((s) => only.includes(s.name)) : shots;

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    this.waiters = [];
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
        return;
      }
      if (msg.method) {
        this.waiters = this.waiters.filter((w) => {
          if (w.method !== msg.method) return true;
          w.resolve(msg.params);
          return false;
        });
      }
    };
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`CDP timeout: ${method}`));
        }
      }, 15000);
    });
  }
  once(method, timeout = 15000) {
    return new Promise((resolve, reject) => {
      const waiter = { method, resolve };
      this.waiters.push(waiter);
      setTimeout(() => {
        this.waiters = this.waiters.filter((w) => w !== waiter);
        reject(new Error(`event timeout: ${method}`));
      }, timeout);
    });
  }
}

async function main() {
  const profile = path.join(BASE, 'tests', 'profiles', 'cdp');
  fs.rmSync(profile, { recursive: true, force: true });
  fs.mkdirSync(profile, { recursive: true });
  const chrome = spawn(CHROME, [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-background-networking',
    '--hide-scrollbars',
    '--force-color-profile=srgb',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    'about:blank',
  ], { stdio: 'ignore' });

  let wsUrl = null;
  for (let i = 0; i < 80; i++) {
    try {
      const info = await httpJson(`http://${HOST}:${PORT}/json/version`);
      wsUrl = info.webSocketDebuggerUrl;
      break;
    } catch { await sleep(150); }
  }
  if (!wsUrl) { chrome.kill('SIGKILL'); throw new Error('DevTools endpoint never came up'); }

  const page = await httpPutJson(`http://${HOST}:${PORT}/json/new?about:blank`);
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  const cdp = new CDP(ws);

  const errors = [];
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === 'Runtime.exceptionThrown') {
      errors.push(`${msg.params.exceptionDetails.text} ${msg.params.exceptionDetails.exception?.description || ''}`.trim());
    }
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      errors.push('console: ' + msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
    }
  });

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');

  const results = [];
  for (const shot of queue) {
    await cdp.send('Network.clearBrowserCookies');
    if (shot.who) {
      const value = SEED.cookies[shot.who];
      if (!value) throw new Error(`no cookie for ${shot.who}`);
      await cdp.send('Network.setCookie', {
        name: 'classsite_session', value, domain: HOST, path: '/', httpOnly: true, sameSite: 'Lax',
      });
    }
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: shot.w, height: shot.h, deviceScaleFactor: 2, mobile: shot.w < 700,
    });
    await cdp.send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-color-scheme', value: shot.scheme || 'light' }],
    });

    const loaded = cdp.once('Page.loadEventFired');
    await cdp.send('Page.navigate', { url: SITE + shot.url });
    await loaded;
    await sleep(350);

    const probe = await cdp.send('Runtime.evaluate', {
      expression: `JSON.stringify({
        title: document.title,
        h1: document.querySelector('h1,h2')?.textContent?.trim() || '',
        scrollW: document.documentElement.scrollWidth,
        innerW: innerWidth,
        scrollH: document.documentElement.scrollHeight,
        innerH: innerHeight
      })`,
      returnByValue: true,
    });
    const info = JSON.parse(probe.result.value);

    let params = { format: 'png', fromSurface: true, captureBeyondViewport: !!shot.full };
    if (shot.full) {
      const metrics = await cdp.send('Page.getLayoutMetrics');
      const size = metrics.cssContentSize || metrics.contentSize;
      params.clip = { x: 0, y: 0, width: shot.w, height: Math.min(size.height, 4200), scale: 1 };
    }
    const { data } = await cdp.send('Page.captureScreenshot', params);
    const file = path.join(SHOTS_DIR, shot.name + '.png');
    fs.writeFileSync(file, Buffer.from(data, 'base64'));

    const overflow = info.scrollW > info.innerW + 1;
    results.push({ name: shot.name, overflow, ...info, file });
    console.log(`${overflow ? 'OVERFLOW' : 'ok      '} ${shot.name.padEnd(22)} ${info.title} | ${info.h1} | ${info.scrollW}x${info.scrollH}`);
  }

  if (errors.length) console.log('\nJS errors:\n' + [...new Set(errors)].join('\n'));
  const bad = results.filter((r) => r.overflow);
  if (bad.length) console.log('\nHorizontally overflowing: ' + bad.map((r) => r.name).join(', '));
  console.log(`\n${results.length} screenshots in ${SHOTS_DIR}`);

  ws.close();
  chrome.kill('SIGKILL');
}

main().catch((e) => {
  console.error('FAILED', e);
  process.exitCode = 1;
});
