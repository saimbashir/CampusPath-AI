/* Pre-render every CampusPath 3D character pose and reaction with the project's own CP3D renderer
   (app/static/cp3d.js) into small animated WebP images in app/static/characters/.
   The site shows these by default, so no live WebGL runs and nothing can freeze the browser.
   Live 3D remains available with ?cp3d=live.

   Re-run only after changing characters in mascot.js or cp3d.js, with the app running:
     npm install playwright sharp
     node scripts/bake_characters.cjs http://127.0.0.1:8000        (CP_CHANNEL=chrome to use installed Chrome) */
const path = require('path'), fs = require('fs');
const { chromium } = require('playwright');
const sharp = require('sharp');
const BASE = process.argv[2] || 'http://127.0.0.1:8000';
const OUT = path.resolve(__dirname, '..', 'app', 'static', 'characters');
const W = 280, H = 224, FPS = 10, T0 = 0.8;

function times(motion) {
  if (motion === 'flip') return { t: Array.from({ length: 12 }, (_, i) => T0 + i / FPS), back: false };
  if (motion === 'champion') return { t: Array.from({ length: 36 }, (_, i) => i / FPS), back: false };
  return { t: Array.from({ length: 16 }, (_, i) => T0 + i / FPS), back: true };   // boomerang loop
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: process.env.CP_CHANNEL || undefined, args: process.env.CP_SOFTWARE_GL ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [] });
  const page = await browser.newPage();
  page.on('pageerror', e => console.error('page error:', e.message));
  await page.goto(BASE + '/?cp3d=force');
  await page.waitForFunction(() => window.CampusMascot && window.CP3D);
  // Every pose the app can show: screens, results, inline stages, plus a default and each reaction per character.
  const jobs = await page.evaluate(() => {
    const M = window.CampusMascot, o = (t, c) => ({ t, c: { gold: '#ffd43b', pink: '#ff6b9a', blue: '#4dabf7', green: '#51cf66', purple: '#b197fc', orange: '#ff922b', teal: '#20c997', red: '#ff6b6b' }[c] || c });
    const one = (c, motion, prop, orbs, face) => ({ c, motion, prop: prop || 'none', orbs: orbs || [], face });
    const poses = [];
    const add = (c, xs) => poses.push({ c, xs });
    for (const table of [M.tables.STUDENT, M.tables.TEACHER, M.tables.ADMIN]) for (const r of Object.values(table)) add({ c: r[0], motion: r[1], prop: r[2], orbs: r[3], acc: r[5] }, false);
    for (const t of Object.values(M.tables.TIERS)) for (const c of t.chars) add(c, false);
    [one('ruby', 'shrug', 'none', [o('orb', 'red'), o('ring', 'blue')], { eyes: 0, mouth: 2, brow: 1 }), one('pip', 'point', 'bulb', [o('star', 'gold'), o('orb', 'pink')]),
     Object.assign(one('drizzle', 'idle', 'none', [o('ring', 'blue'), o('star', 'gold')]), { acc: ['headphones'] }), one('coco', 'idle', 'none', [o('star', 'gold'), o('ring', 'purple'), o('heart', 'pink')]),
     one('puff', 'strut', 'magnifier', [o('orb', 'blue'), o('star', 'gold')]), one('blip', 'type', 'laptop', [o('gem', 'blue'), o('ring', 'teal')]),
     one('mo', 'present', 'pointer', [o('cube', 'orange'), o('cube', 'blue')]), one('pip', 'wave', 'none', [o('star', 'gold'), o('orb', 'pink')]), one('nova', 'cheer', 'trophy', [o('star', 'gold'), o('gem', 'teal')], { eyes: 2, mouth: 1 }),
     one('kiwi', 'wave', 'key', [o('cube', 'blue'), o('star', 'gold')]), one('pip', 'point', 'bulb', [o('orb', 'pink'), o('ring', 'blue')])].forEach(c => add(c, false));
    [one('pip', 'wave', 'none', []), one('mo', 'idle', 'none', []), one('luma', 'idle', 'none', []), one('pip', 'idle', 'none', [])].forEach(c => add(c, true));
    const out = new Map();
    for (const p of poses) {
      const spec = M.cast[p.c.c];
      const face = Object.assign(M.baseFace(spec), p.c.face || {});
      out.set(M.stillKey(p.c, p.xs), { c: p.c.c, motion: p.c.motion || 'idle', prop: p.c.prop === undefined ? 'none' : p.c.prop, acc: p.c.acc, orbs: p.xs ? [] : (p.c.orbs || []).slice(0, 4), face });
    }
    for (const name of Object.keys(M.cast)) {
      const base = M.baseFace(M.cast[name]);
      out.set(name, { c: name, motion: 'idle', prop: 'none', orbs: [], face: base });
      for (const [mood, r] of Object.entries(M.reactions)) out.set(name + '-' + mood, { c: name, motion: r.motion, prop: r.prop || 'none', orbs: [], face: Object.assign({}, base, r.face) });
    }
    return [...out.entries()];
  });
  console.log(jobs.length + ' clips');
  let bytes = 0, n = 0;
  for (const [key, job] of jobs) {
    const tl = times(job.motion);
    const frames = await page.evaluate(async ({ job, t, W, H }) => {
      const spec = window.CampusMascot.cast[job.c];
      let c = null;
      for (let i = 0; i < 200 && !c; i++) { c = window.CP3D.still(spec, job, W, H, t[0]); if (!c) await new Promise(r => setTimeout(r, 50)); }
      if (!c) throw new Error('3D renderer not ready: ' + JSON.stringify(window.CP3D.stats()));
      const urls = [];
      for (const ti of t) urls.push(window.CP3D.still(spec, job, W, H, ti).toDataURL('image/png'));
      return urls;
    }, { job, t: tl.t, W, H });
    let bufs = frames.map(u => Buffer.from(u.split(',')[1], 'base64'));
    const alpha = (await sharp(bufs[0]).extractChannel(3).stats()).channels[0].max;
    if (alpha < 10) throw new Error('blank frame for ' + key);
    if (tl.back) bufs = bufs.concat(bufs.slice(1, -1).reverse());
    const file = path.join(OUT, key + '.webp');
    await sharp(bufs, { join: { animated: true } }).webp({ quality: 72, alphaQuality: 90, effort: 5, loop: 0, delay: 1000 / FPS }).toFile(file);
    bytes += fs.statSync(file).size; n++;
    if (n % 20 === 0) console.log(n + '/' + jobs.length);
  }
  console.log(`${n} clips, ${(bytes / 1e6).toFixed(1)} MB in ${OUT}`);
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
