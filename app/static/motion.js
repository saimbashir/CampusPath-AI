/* CampusPath AI · interaction polish (progressive enhancement; the app works without it).
   1. Cursor spotlight on cards (fine pointers only)
   2. Count-up for numeric stat tiles
   3. Mobile navigation drawer: Escape and tap-outside dismiss, focus returns to the menu button
   4. 3D pointer tilt on cards, stats and feature tiles
   5. 3D scroll reveal for content below the fold */
(function () {
  'use strict';

  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');

  /* 0. Lighter effects (v0.9.2) on low-power devices, Save-Data, and browsers whose WebGL is
        software-rendered (cp3d.js reports that with cp3d-lost). Same design, fewer blurs and
        no continuously repainting decorations; see .cp-lite in motion.css. */
  const cores = navigator.hardwareConcurrency || 8, mem = navigator.deviceMemory || 8;
  const lite = function () { document.documentElement.classList.add('cp-lite'); };
  if (cores <= 2 || mem <= 2 || (cores <= 4 && mem <= 4) || (navigator.connection && navigator.connection.saveData)) lite();
  window.addEventListener('cp3d-lost', lite);

  /* 1. Spotlight: moves a soft highlight with the pointer across the card under it. */
  let frame = 0;
  let pending = null;
  document.addEventListener('pointermove', function (event) {
    if (!finePointer.matches || reduce.matches) return;
    const card = event.target && event.target.closest ? event.target.closest('.card') : null;
    if (!card) return;
    pending = { card: card, x: event.clientX, y: event.clientY };
    if (frame) return;
    frame = requestAnimationFrame(function () {
      frame = 0;
      const rect = pending.card.getBoundingClientRect();
      pending.card.style.setProperty('--mx', (pending.x - rect.left) + 'px');
      pending.card.style.setProperty('--my', (pending.y - rect.top) + 'px');
    });
  }, { passive: true });

  /* 2. Count-up: numbers such as "85%" or "4" ease up from zero once, when first rendered. */
  const numeric = /^(\d+(?:\.\d+)?)(%?)$/;
  function countUp(el) {
    if (el.dataset.counted) return;
    const text = el.textContent.trim();
    const match = numeric.exec(text);
    if (!match) return;
    el.dataset.counted = '1';
    if (reduce.matches) return;
    const target = Number(match[1]);
    const suffix = match[2];
    const decimals = match[1].indexOf('.') === -1 ? 0 : 1;
    const started = performance.now();
    const duration = 900;
    el.textContent = (0).toFixed(decimals) + suffix;
    function step(now) {
      const t = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = t < 1 ? (target * eased).toFixed(decimals) + suffix : text;
      if (t < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  function scanStats(root) {
    if (!root || !root.querySelectorAll) return;
    if (root.matches && root.matches('.stat strong')) countUp(root);
    root.querySelectorAll('.stat strong').forEach(countUp);
  }
  new MutationObserver(function (records) {
    records.forEach(function (record) {
      record.addedNodes.forEach(function (node) {
        if (node.nodeType === 1) scanStats(node);
      });
    });
  }).observe(document.body, { childList: true, subtree: true });
  scanStats(document.body);

  /* 3. Mobile navigation: close with Escape or a tap outside, and return focus to the menu button. */
  function drawer() { return document.querySelector('.sidebar'); }
  function menuButton() { return document.querySelector('.menu-toggle'); }
  function closeDrawer(returnFocus) {
    const panel = drawer();
    if (!panel || !panel.classList.contains('open')) return;
    panel.classList.remove('open');
    const button = menuButton();
    if (button) {
      button.setAttribute('aria-expanded', 'false');
      if (returnFocus) button.focus();
    }
  }
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeDrawer(true);
  });
  document.addEventListener('click', function (event) {
    const panel = drawer();
    if (!panel || !panel.classList.contains('open')) return;
    if (panel.contains(event.target)) return;
    if (event.target.closest && event.target.closest('.menu-toggle')) return;
    closeDrawer(false);
  });
  /* 4. 3D tilt: cards, stats and feature tiles lean towards the pointer (fine pointers only).
        Cards that hold a form, chart or table stay steady so typing and reading are never disturbed. */
  const TILT = '.content .card, .content .stat, .content .next-card, .features .feature';
  let tiltEl = null;
  let tiltFrame = 0;
  let tiltPoint = null;
  function untilt(el) {
    if (!el) return;
    el.classList.remove('cp3d-tilt');
    ['--t3x', '--t3y', '--t3x-n', '--t3y-n'].forEach(function (k) { el.style.removeProperty(k); });
  }
  function steady(el) { return !!el.querySelector('form, textarea, input, select, table, .graph, canvas'); }
  document.addEventListener('pointermove', function (event) {
    if (!finePointer.matches || reduce.matches) return;
    const el = event.target && event.target.closest ? event.target.closest(TILT) : null;
    if (el !== tiltEl) { untilt(tiltEl); tiltEl = el && !steady(el) ? el : null; }
    if (!tiltEl) return;
    tiltPoint = { x: event.clientX, y: event.clientY };
    if (tiltFrame) return;
    tiltFrame = requestAnimationFrame(function () {
      tiltFrame = 0;
      if (!tiltEl || !tiltPoint) return;
      const r = tiltEl.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const nx = Math.max(-0.5, Math.min(0.5, (tiltPoint.x - r.left) / r.width - 0.5)) * 2;
      const ny = Math.max(-0.5, Math.min(0.5, (tiltPoint.y - r.top) / r.height - 0.5)) * 2;
      // Big cards lean a little, small tiles lean more; very tall cards barely move.
      const max = tiltEl.matches('.stat, .feature') ? 9 : Math.max(1.2, Math.min(4, 900 / r.height));
      tiltEl.style.setProperty('--t3x', (nx * max).toFixed(2) + 'deg');
      tiltEl.style.setProperty('--t3y', (-ny * max * 0.8).toFixed(2) + 'deg');
      tiltEl.style.setProperty('--t3x-n', nx.toFixed(3));
      tiltEl.style.setProperty('--t3y-n', ny.toFixed(3));
      tiltEl.classList.add('cp3d-tilt');
    });
  }, { passive: true });
  document.addEventListener('pointerout', function (event) {
    if (tiltEl && (!event.relatedTarget || !tiltEl.contains(event.relatedTarget))) { untilt(tiltEl); tiltEl = null; }
  }, { passive: true });
  window.addEventListener('blur', function () { untilt(tiltEl); tiltEl = null; });

  /* 5. Scroll reveal: blocks that start below the fold rise in 3D when they scroll into view. */
  if ('IntersectionObserver' in window) {
    const REVEAL = '.content .card, .content .stat, .content .list-item, .content .next-card, .features .feature';
    const io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove('cp3d-wait');
        entry.target.classList.add('cp3d-in');
        io.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.06 });
    let revealFrame = 0;
    function scanReveal() {
      revealFrame = 0;
      if (reduce.matches) return;
      const limit = window.innerHeight * 0.96;
      document.querySelectorAll(REVEAL).forEach(function (el) {
        if (el.dataset.cp3d) return;
        el.dataset.cp3d = '1';
        const r = el.getBoundingClientRect();
        if (r.height && r.top > limit) { el.classList.add('cp3d-wait'); io.observe(el); }
      });
    }
    new MutationObserver(function (records) {
      if (revealFrame) return;
      // Ignore the animated characters' own updates (speech bubbles type every few ms).
      const relevant = records.some(function (r) { return !(r.target.closest && r.target.closest('.cp-stage')); });
      if (relevant) revealFrame = requestAnimationFrame(scanReveal);
    }).observe(document.body, { childList: true, subtree: true });
    scanReveal();
  }
})();

/* 6. 3D page transitions (v0.8.0). Each screen has its own 3D move: cube turn, card flip,
      door swing, depth zoom, page fold or tilt-swing. The direction follows the menu order,
      so going "forward" and "back" feel different. app.js calls leave() before a screen is
      replaced and enter() once the new screen is drawn. */
(function () {
  'use strict';
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const STYLES = ['cube', 'flip', 'door', 'zoom', 'fold', 'swing'];
  const FIXED = {
    dashboard: 'zoom', courses: 'cube', path: 'door', tutor: 'flip', quiz: 'swing', graph: 'zoom',
    'formal-viva': 'flip', voice: 'cube', materials: 'fold', assignments: 'door', planner: 'fold',
    lab: 'cube', analytics: 'swing', notifications: 'flip', settings: 'door', students: 'cube',
    topics: 'zoom', questions: 'swing', copilot: 'flip', 'oral-review': 'fold', 'viva-analytics': 'swing',
    'viva-review': 'door', structure: 'fold', research: 'zoom'
  };
  let last = null;
  let lastIndex = 0;
  function styleFor(page) {
    if (FIXED[page]) return FIXED[page];
    let h = 0; for (const ch of String(page)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return STYLES[h % STYLES.length];
  }
  function indexOf(page) {
    const buttons = Array.prototype.slice.call(document.querySelectorAll('[data-nav]'));
    const i = buttons.findIndex(b => b.dataset.nav === page && b.closest('.nav'));
    return i < 0 ? lastIndex : i;
  }
  function clear(main) { main.className = main.className.replace(/\bpt-[\w-]+/g, '').trim(); }
  function wait(main, ms) {
    return new Promise(function (resolve) {
      let done = false;
      const finish = function () { if (done) return; done = true; main.removeEventListener('animationend', onEnd); resolve(); };
      const onEnd = function (e) { if (e.target === main) finish(); };
      main.addEventListener('animationend', onEnd);
      setTimeout(finish, ms);
    });
  }
  window.CampusTransition = {
    leave: async function (page) {
      const main = document.querySelector('#main.content');
      if (!main || reduce.matches || !main.firstElementChild || main.querySelector(':scope > .loading')) return;
      const dir = indexOf(page) >= lastIndex ? 'pt-fwd' : 'pt-back';
      clear(main);
      main.classList.add('pt-leave', 'pt-' + styleFor(last || page), dir);
      await wait(main, 320);
    },
    enter: function (page) {
      const main = document.querySelector('#main.content');
      const idx = indexOf(page);
      const dir = idx >= lastIndex ? 'pt-fwd' : 'pt-back';
      lastIndex = idx; last = page;
      if (!main) return;
      clear(main);
      if (reduce.matches) return;
      void main.offsetWidth;
      main.classList.add('pt-enter', 'pt-' + styleFor(page), dir);
      if (window.scrollY > 0) window.scrollTo({ top: 0, behavior: 'instant' in document.documentElement.style ? 'instant' : 'auto' });
      wait(main, 900).then(function () { if (main.classList.contains('pt-enter')) clear(main); });
    }
  };
})();
