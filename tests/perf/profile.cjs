// Real-Chrome profiling of CampusPath screens. Usage: node profile.cjs <baseUrl> <label> [extraQuery]
const { chromium } = require('playwright');
// Browser: Chromium from Playwright by default. CP_CHANNEL=chrome|msedge uses your installed
// Chrome/Edge; HEADED=1 shows the window (real GPU); CP_SOFTWARE_GL=1 forces a software GPU.
const LAUNCH = { channel: process.env.CP_CHANNEL || undefined, headless: !process.env.HEADED, args: process.env.CP_SOFTWARE_GL ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [] };
const fs = require('fs');
const base = process.argv[2], label = process.argv[3], q = process.argv[4] || '';

function chromeCpu() { // total CPU seconds of every Chrome process (renderer + GPU + browser)
  let t = 0;
  for (const pid of fs.readdirSync('/proc').filter(x => /^\d+$/.test(x))) {
    try {
      const cmd = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8');
      if (!/chrome/i.test(cmd)) continue;
      const f = fs.readFileSync(`/proc/${pid}/stat`, 'utf8').split(') ')[1].split(' ');
      t += (Number(f[11]) + Number(f[12])) / 100;
    } catch {}
  }
  return t;
}
const INSTRUMENT = () => {
  window.__m = { long: [], lag: [], frames: 0, lcp: 0, cls: 0, errors: [] };
  try { new PerformanceObserver(l => l.getEntries().forEach(e => __m.long.push(e.duration))).observe({ type: 'longtask', buffered: true }); } catch {}
  try { new PerformanceObserver(l => l.getEntries().forEach(e => { __m.lcp = e.startTime; })).observe({ type: 'largest-contentful-paint', buffered: true }); } catch {}
  try { new PerformanceObserver(l => l.getEntries().forEach(e => { if (!e.hadRecentInput) __m.cls += e.value; })).observe({ type: 'layout-shift', buffered: true }); } catch {}
  (function lag() { const t = performance.now(); setTimeout(() => { __m.lag.push(performance.now() - t - 50); lag(); }, 50); })();
  (function f() { __m.frames++; requestAnimationFrame(f); })();
};

async function scenario(browser, name, role, path, action) {
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 800 } });
  if (role) await ctx.addCookies([{ name: 'mock', value: role, url: base }]);
  const page = await ctx.newPage();
  const errors = []; const failed = [];
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errors.push(m.type() + ': ' + m.text().slice(0, 160)); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', r => failed.push(r.url()));
  page.on('response', r => { if (r.status() >= 400 && !r.url().includes('/api/auth/me')) failed.push(r.status() + ' ' + r.url()); });
  await page.addInitScript(INSTRUMENT);
  const cdp = await ctx.newCDPSession(page); await cdp.send('Performance.enable');
  const cpu0 = chromeCpu(); const t0 = Date.now();
  await page.goto(base + path + q, { waitUntil: 'load' });
  // time until the app is interactive: real content rendered and an input round-trip is fast
  const ready = await page.evaluate(async () => { const s = performance.now(); while (!document.querySelector('#root h1')) await new Promise(r => setTimeout(r, 20)); return performance.now(); });
  // input responsiveness: click something and time until the next paint
  let clickMs = null;
  if (action) clickMs = await page.evaluate(action);
  await page.waitForTimeout(6000);
  const cpu1 = chromeCpu(); const wall = (Date.now() - t0) / 1000;
  const m = await page.evaluate(() => {
    const lag = __m.lag.slice(10); lag.sort((a, b) => a - b);
    const canv = [...document.querySelectorAll('.cp-char canvas')].filter(c => c.width > 4);
    return { lcp: Math.round(__m.lcp), cls: +__m.cls.toFixed(3), longTasks: __m.long.length, longMax: Math.round(Math.max(0, ...__m.long)), longTotal: Math.round(__m.long.reduce((a, b) => a + b, 0)),
      lagP95: Math.round(lag[Math.floor(lag.length * .95)] || 0), lagMax: Math.round(lag[lag.length - 1] || 0), rafFps: +(__m.frames / (performance.now() / 1000)).toFixed(1),
      chars: document.querySelectorAll('.cp-char').length, canvases3d: canv.length, fallbacks: document.querySelectorAll('.cp-fallback').length,
      px: canv.reduce((a, c) => a + c.width * c.height, 0), hscroll: document.documentElement.scrollWidth > innerWidth };
  });
  const pm = Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(x => [x.name, x.value]));
  const res = { scenario: name, readyMs: Math.round(ready), clickMs, ...m, heapMB: +(pm.JSHeapUsedSize / 1e6).toFixed(1), chromeCpuPct: Math.round((cpu1 - cpu0) / wall * 100), errors: errors.slice(0, 6), failed: failed.slice(0, 6) };
  await ctx.close();
  return res;
}
const clickSignIn = async () => { const t = performance.now(); document.querySelector('[data-action="login"]').click(); while (!document.querySelector('.auth-card')) await new Promise(r => requestAnimationFrame(r)); await new Promise(r => requestAnimationFrame(r)); return Math.round(performance.now() - t); };
const clickNav = async () => { const t = performance.now(); document.querySelector('[data-nav="path"]').click(); while (!document.querySelector('.path-item')) await new Promise(r => requestAnimationFrame(r)); return Math.round(performance.now() - t); };

(async () => {
  const browser = await chromium.launch(LAUNCH);
  const out = [];
  out.push(await scenario(browser, 'landing', null, '/', clickSignIn));
  out.push(await scenario(browser, 'login', null, '/login'));
  out.push(await scenario(browser, 'student-dashboard', 'student', '/app', clickNav));
  out.push(await scenario(browser, 'teacher-dashboard', 'teacher', '/app'));
  // refresh stress: 5 consecutive reloads of the student dashboard
  {
    const ctx = await browser.newContext({ viewport: { width: 1366, height: 800 } });
    await ctx.addCookies([{ name: 'mock', value: 'student', url: base }]);
    const page = await ctx.newPage(); const times = [];
    for (let i = 0; i < 5; i++) { const t = Date.now(); await page.goto(base + '/app' + q); await page.waitForSelector('#root h1', { timeout: 120000 }); times.push(Date.now() - t); await page.waitForTimeout(300); }
    const nav = [];
    for (const p of ['courses', 'path', 'quiz', 'graph', 'materials', 'analytics', 'dashboard', 'settings', 'planner', 'dashboard']) { const t = Date.now(); await page.evaluate(p => document.querySelector(`[data-nav="${p}"]`)?.click(), p); await page.waitForTimeout(120); nav.push(Date.now() - t); }
    await page.waitForTimeout(1500);
    const live = await page.evaluate(() => ({ chars: document.querySelectorAll('.cp-char').length, heap: performance.memory ? +(performance.memory.usedJSHeapSize / 1e6).toFixed(1) : null }));
    out.push({ scenario: 'refresh-x5+rapid-nav', reloadMs: times, rapidNavMs: nav, ...live });
    await ctx.close();
  }
  await browser.close();
  fs.writeFileSync(`result-${label}.json`, JSON.stringify(out, null, 1));
  console.log(JSON.stringify(out, null, 1));
})();
