/* CampusPath AI · 3D character director (v0.9.5)
   Places the CP3D characters (cp3d.js) on every screen and drives their behaviour.
   - 15 original characters, each with its own shape, colour, accessory and personality.
   - Every student and teacher screen has its own character doing a job that matches the
     screen (reading for materials, writing for quizzes, typing for the lab, a mic for the viva…)
     with themed 3D objects orbiting them. Their eyeballs follow the orbiting objects.
   - Results react to the score: full marks → crown + trophy + back-flip; good → cheering;
     pass → relieved; below average → crying under a rain cloud while a friend hugs them.
   - Server busy → thinking; success → cheer; error → puzzled; viva mic on → listening;
     question playing → talking. Tap any character and it does a back-flip.
   Progressive enhancement: decorates what app.js renders and never touches data. */
(function () {
  'use strict';

  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const html = document.documentElement;
  let uid = 0;

  function app() { return typeof state !== 'undefined' ? state : null; }
  function role() { const s = app(); return (s && s.user && s.user.role) || 'guest'; }
  function page() { const s = app(); return (s && s.page) || 'dashboard'; }
  const TITLES = /^(dr|prof|professor|mr|mrs|ms|miss|sir|madam|engr|eng|hafiz|syed|sheikh|muhammad|m)\.?$/i;
  function firstName() {
    const s = app();
    if (!s || !s.user || !s.user.name) return '';
    const parts = String(s.user.name).trim().split(/\s+/);
    const name = parts.find(w => !TITLES.test(w)) || parts[0];
    return name.length > 16 ? name.slice(0, 16) : name;
  }

  /* ======================================================================
     1. The cast — 15 original characters
        body: 0 round · 1 bean · 2 soft cube · 3 drop · 4 wide mochi
     ====================================================================== */
  const CAST = {
    pip:     { name: 'Pip',          emoji: '🌱', color: '#ffcf3f', body: 0, acc: ['sprout'], foot: '#ff8a3d', iris: '#6b3d1e', blush: 1, mouth: 1 },
    mo:      { name: 'Professor Mo', emoji: '🎓', color: '#4fd1b0', body: 1, acc: ['gradcap', 'glasses'], foot: '#2f6f73', iris: '#2b4a6b', mouth: 0 },
    coco:    { name: 'Coco',         emoji: '🎧', color: '#ff7a8a', body: 0, acc: ['headphones'], accA: '#7c5cff', accB: '#ffd43b', foot: '#5b3a8a', iris: '#3a2346', blush: 1, mouth: 1 },
    blip:    { name: 'Blip',         emoji: '🤖', color: '#5ab8ff', body: 2, acc: ['antenna'], accA: '#ff4d6d', foot: '#2b4a8a', iris: '#163a63', mouth: 0 },
    luma:    { name: 'Luma',         emoji: '😇', color: '#b69cff', body: 3, acc: ['halo'], foot: '#5f4bb6', iris: '#3b2a6b', blush: 1, mouth: 0 },
    tango:   { name: 'Tango',        emoji: '🥳', color: '#ff9f43', body: 0, acc: ['partyhat'], accA: '#4dabf7', accB: '#ff6b9a', foot: '#a34d12', iris: '#4a2a12', blush: 1, mouth: 1 },
    kiwi:    { name: 'Kiwi',         emoji: '🧢', color: '#94d82d', body: 1, acc: ['cap'], accA: '#ff6b6b', accB: '#c92a2a', foot: '#2b8a3e', iris: '#2b3a12', mouth: 1 },
    nova:    { name: 'Nova',         emoji: '👑', color: '#9b6bff', body: 0, acc: ['crown'], foot: '#4b2fa3', iris: '#2e1a5b', blush: 1, mouth: 1 },
    drizzle: { name: 'Drizzle',      emoji: '💧', color: '#8fb4ff', body: 3, acc: [], accA: '#ff922b', accB: '#ffd43b', foot: '#3b5bdb', iris: '#1f3a7a', mouth: 0 },
    sage:    { name: 'Sage',         emoji: '🤓', color: '#2ec4b6', body: 0, acc: ['glasses'], foot: '#0b7285', iris: '#0b3a4a', mouth: 0 },
    peach:   { name: 'Peach',        emoji: '🎀', color: '#ffb38a', body: 4, acc: ['bow'], accA: '#ff6b9a', accB: '#ff8fb1', foot: '#c2410c', iris: '#5a2a1a', blush: 1, mouth: 1 },
    atlas:   { name: 'Atlas',        emoji: '🧭', color: '#4d8dff', body: 1, acc: ['beanie'], accA: '#ffa94d', accB: '#fff3bf', foot: '#1c3f95', iris: '#14254a', mouth: 0 },
    inky:    { name: 'Inky',         emoji: '✏️', color: '#7c8cff', body: 2, acc: ['beret'], accA: '#e64980', foot: '#3b3f9e', iris: '#1d1f5e', mouth: 0 },
    ruby:    { name: 'Ruby',         emoji: '🔍', color: '#ff6b81', body: 4, acc: [], foot: '#a61e4d', iris: '#4a1222', blush: 1, mouth: 1 },
    puff:    { name: 'Puff',         emoji: '☁️', color: '#eef0ff', body: 0, acc: [], foot: '#8c94c7', iris: '#3b4270', blush: 1, mouth: 0 }
  };
  const C = { gold: '#ffd43b', pink: '#ff6b9a', blue: '#4dabf7', green: '#51cf66', purple: '#b197fc', orange: '#ff922b', teal: '#20c997', red: '#ff6b6b' };
  const o = (t, c) => ({ t: t, c: C[c] || c });

  /* Face presets for reactions. eyes: 0 eyeballs · 1 happy ^^ · 2 stars · 4 shut
     mouth: 0 smile · 1 grin · 2 "o" · 3 frown · 4 crying · 5 flat · 6 talking · 7 smirk */
  const REACT = {
    think:  { motion: 'think',  face: { eyes: 0, mouth: 7, brow: 3 }, dropProp: 1 },
    cheer:  { motion: 'cheer',  face: { eyes: 2, mouth: 1, brow: 1 } },
    sad:    { motion: 'cry',    face: { eyes: 0, mouth: 4, brow: 2, tears: 1, lid: [0.3, 0.3, 0.6] }, dropProp: 1 },
    oops:   { motion: 'shrug',  face: { eyes: 0, mouth: 2, brow: 1 }, dropProp: 1 },
    listen: { motion: 'listen', face: { eyes: 0, mouth: 0 }, dropProp: 1 },
    talk:   { motion: 'talk',   face: { eyes: 0, mouth: 6 }, prop: 'mic' },
    poke:   { motion: 'flip',   face: { eyes: 1, mouth: 1 }, dropProp: 1 }
  };

  /* ======================================================================
     2. Screens — each one gets a character doing that screen's job.
        [character, motion, prop, orbiting objects, speech lines, accessory override]
     ====================================================================== */
  const STUDENT = {
    dashboard:     ['pip', 'point', 'bulb', [o('star', 'gold'), o('orb', 'pink'), o('ring', 'blue'), o('gem', 'teal')], ['Here is your best next step 🎯', 'Small daily practice beats cramming 💪', 'I picked this from your latest answers.']],
    courses:       ['kiwi', 'wave', 'key', [o('cube', 'orange'), o('cube', 'blue'), o('cube', 'green'), o('cube', 'purple')], ["Join a course with your teacher's code 🔑", 'Any department, any subject. I adapt to it.']],
    path:          ['atlas', 'walk', 'compass', [o('gem', 'teal'), o('gem', 'orange'), o('check', 'green')], ['Strong foundations first, then the big ideas 🧱', 'Each step unlocks the next one 🔓']],
    tutor:         ['sage', 'read', 'book', [o('orb', 'gold'), o('star', 'blue'), o('ring', 'purple')], ['Ask me anything from your course material 📖', 'I show the exact source I used 🔖', 'Try "explain it step by step".']],
    quiz:          ['inky', 'write', 'pencil', [o('check', 'green'), o('star', 'gold'), o('ring', 'blue')], ['Ready for a quick check-in? ✍️', 'Mistakes show me what to explain next 🙂']],
    graph:         ['ruby', 'strut', 'magnifier', [o('orb', 'blue'), o('orb', 'pink'), o('orb', 'green'), o('orb', 'gold')], ['Every concept is connected 🔗', 'Tap a concept to study it.']],
    'formal-viva': ['coco', 'talk', 'mic', [o('star', 'gold'), o('star', 'pink'), o('ring', 'purple')], ['Speak clearly and take your time 🎤', 'Your teacher confirms the final marks.']],
    voice:         ['drizzle', 'listen', 'none', [o('heart', 'pink'), o('ring', 'blue'), o('orb', 'teal')], ['Practise out loud. No marks here 😊', 'Explain it as if you were teaching a friend.'], ['headphones']],
    materials:     ['puff', 'read', 'book', [o('cube', 'blue'), o('cube', 'orange'), o('cube', 'green')], ['Upload notes, slides or PDFs 📄', 'I read them so the tutor can cite them.']],
    assignments:   ['nova', 'guard', 'clipboard', [o('check', 'green'), o('star', 'gold'), o('cube', 'purple')], ['Submit before the deadline ⏰', 'You get a notification when it is graded 🔔']],
    planner:       ['peach', 'ring', 'clock', [o('orb', 'pink'), o('ring', 'gold'), o('heart', 'red')], ['A little every day adds up 🗓️', 'Missed a day? I reschedule it 🔁']],
    lab:           ['blip', 'type', 'laptop', [o('gem', 'blue'), o('cube', 'teal'), o('ring', 'orange')], ['Step through the search one move at a time 🧩']],
    analytics:     ['mo', 'strut', 'chart', [o('star', 'gold'), o('gem', 'teal'), o('orb', 'blue')], ['Look how far you have come 📈', 'The lowest bar is your quickest win 🏆']],
    notifications: ['tango', 'ring', 'bell', [o('star', 'gold'), o('heart', 'pink'), o('orb', 'blue')], ['Fresh updates from your courses 🔔']],
    settings:      ['luma', 'guard', 'shield', [o('ring', 'purple'), o('gem', 'teal'), o('orb', 'gold')], ['Make CampusPath yours ⚙️', 'Your progress stays private 🔒']]
  };
  const TEACHER = {
    dashboard:        ['mo', 'present', 'pointer', [o('cube', 'orange'), o('cube', 'blue'), o('cube', 'green'), o('star', 'gold')], ['Here is where your class stands today 📊', 'I flag students who may need support 🤝']],
    courses:          ['kiwi', 'wave', 'key', [o('cube', 'orange'), o('cube', 'blue'), o('cube', 'purple')], ['Create a section for any subject 🏫', 'Share the enrollment code with your class 🔑']],
    students:         ['pip', 'hug', 'heart', [o('heart', 'pink'), o('star', 'gold'), o('orb', 'teal')], ['Every student, one clear view 👥', 'Sort by readiness to find who needs help.']],
    topics:           ['ruby', 'strut', 'magnifier', [o('orb', 'blue'), o('orb', 'pink'), o('orb', 'green'), o('orb', 'gold')], ['Link prerequisites so paths make sense 🔗']],
    materials:        ['puff', 'read', 'book', [o('cube', 'blue'), o('cube', 'orange'), o('cube', 'green')], ['Upload a book, slides or notes 📤', 'Questions are written from your material only 📚']],
    questions:        ['inky', 'write', 'pencil', [o('check', 'green'), o('ring', 'purple'), o('star', 'gold')], ['Review drafts before students see them ✅', 'Generate a batch from any chapter 📝']],
    assignments:      ['nova', 'guard', 'clipboard', [o('check', 'green'), o('star', 'gold'), o('cube', 'blue')], ['Set work, then grade it here 🏅']],
    analytics:        ['atlas', 'strut', 'chart', [o('gem', 'teal'), o('orb', 'blue'), o('star', 'gold')], ['Class intelligence at a glance 📊', 'Find the concept that needs a re-teach 🔍']],
    copilot:          ['blip', 'type', 'laptop', [o('orb', 'teal'), o('ring', 'blue'), o('gem', 'purple')], ['Let me suggest a remedial activity 💡']],
    'formal-viva':    ['coco', 'talk', 'mic', [o('star', 'gold'), o('check', 'green'), o('ring', 'purple')], ['Pick the sources, I draft the viva 🎤', 'Nothing reaches students until you approve ✅']],
    'oral-review':    ['drizzle', 'listen', 'none', [o('check', 'green'), o('star', 'gold'), o('ring', 'blue')], ['Listen, adjust and confirm the marks 🏅'], ['headphones']],
    'viva-analytics': ['sage', 'strut', 'chart', [o('orb', 'pink'), o('gem', 'teal'), o('star', 'gold')], ['See which questions were hardest 📊']],
    'viva-review':    ['peach', 'listen', 'none', [o('heart', 'pink'), o('ring', 'purple'), o('orb', 'blue')], ['Practice sessions your students shared 🎧'], ['headphones']],
    structure:        ['luma', 'read', 'book', [o('cube', 'purple'), o('cube', 'teal'), o('cube', 'gold')], ['Books become chapters, topics and outcomes 🗂️']],
    research:         ['tango', 'strut', 'flask', [o('orb', 'green'), o('gem', 'blue'), o('ring', 'pink')], ['Evidence about how well the AI is doing 🔬'], []],
    notifications:    ['tango', 'ring', 'bell', [o('star', 'gold'), o('heart', 'pink'), o('orb', 'blue')], ['Your latest course updates 🔔']],
    settings:         ['luma', 'guard', 'shield', [o('ring', 'purple'), o('gem', 'teal')], ['Your account and preferences ⚙️']]
  };
  const ADMIN = {
    dashboard: ['luma', 'guard', 'shield', [o('ring', 'gold'), o('gem', 'teal'), o('orb', 'purple'), o('star', 'gold')], ['Invite teachers from any department 🔑', 'Every action is recorded in the audit log 📋']],
    settings:  ['blip', 'wave', 'key', [o('gem', 'blue'), o('ring', 'orange')], ['Keep the workspace safe 🛡️']]
  };
  function screenConfig() {
    const table = role() === 'teacher' ? TEACHER : role() === 'admin' ? ADMIN : STUDENT;
    const r = table[page()] || table.dashboard || STUDENT.dashboard;
    const lines = r[4].slice();
    if (page() === 'dashboard' && firstName()) lines.unshift(`Hi ${firstName()}! 👋`);
    return { chars: [{ c: r[0], motion: r[1], prop: r[2], orbs: r[3], acc: r[5] }], lines: lines };
  }

  /* Score tiers (quiz, assigned viva, practice viva). */
  function tier(score) {
    if (score === null || score === undefined || score === '' || isNaN(score)) return 'pending';
    score = Number(score);
    if (score >= 90) return 'top';
    if (score >= 70) return 'good';
    if (score >= 50) return 'pass';
    return 'low';
  }
  const TIERS = {
    top: { face: '🤩', title: 'Outstanding!', confetti: 1,
      chars: [{ c: 'nova', motion: 'champion', prop: 'trophy', face: { eyes: 2, mouth: 1, brow: 1 }, orbs: [o('star', 'gold'), o('gem', 'teal'), o('star', 'pink')] },
              { c: 'tango', motion: 'cheer', prop: 'none', face: { eyes: 1, mouth: 1 }, orbs: [o('star', 'gold'), o('heart', 'pink')] }],
      lines: s => [`${s}%! Full-marks energy 🏆`, 'You absolutely nailed it 🎉', 'Teachers love answers like these ⭐'] },
    good: { face: '😎', title: 'Great work!',
      chars: [{ c: 'kiwi', motion: 'cheer', prop: 'none', face: { eyes: 1, mouth: 1 }, orbs: [o('star', 'gold'), o('check', 'green')] },
              { c: 'pip', motion: 'wave', prop: 'none', face: { eyes: 0, mouth: 1 }, orbs: [o('star', 'blue'), o('orb', 'pink')] }],
      lines: s => [`${s}% — a strong result 🌟`, 'A little polish and you hit the top 🏅'] },
    pass: { face: '😅', title: 'You passed.',
      chars: [{ c: 'peach', motion: 'shrug', prop: 'none', face: { eyes: 0, mouth: 7, brow: 1 }, orbs: [o('orb', 'blue'), o('check', 'green')] },
              { c: 'sage', motion: 'think', prop: 'none', face: { eyes: 0, mouth: 7, brow: 3 }, orbs: [o('ring', 'purple'), o('star', 'gold')] }],
      lines: s => [`${s}%. Phew, you made it 😅`, 'Review the weak spots to move up a level 📚'] },
    low: { face: '😢', title: 'Below average this time.',
      chars: [{ c: 'drizzle', motion: 'cry', prop: 'none', acc: ['raincloud'], face: { eyes: 0, mouth: 4, brow: 2, tears: 1, lid: [0.3, 0.3, 0.6] }, orbs: [o('heart', 'blue')] },
              { c: 'puff', motion: 'hug', prop: 'heart', face: { eyes: 1, mouth: 0 }, orbs: [o('heart', 'pink'), o('star', 'gold')] }],
      lines: s => [`${s}%… oh no, below average 😭`, 'That one hurt. Revise and come back stronger 💪', 'Open your learning path for the gaps 📚'] },
    pending: { face: '⏳', title: 'Awaiting your teacher.',
      chars: [{ c: 'sage', motion: 'think', prop: 'none', face: { eyes: 0, mouth: 7, brow: 3 }, orbs: [o('orb', 'gold'), o('ring', 'blue'), o('check', 'green')] }],
      lines: () => ['Your answers are saved ✅', 'Your teacher confirms the final marks ⏳'] }
  };

  /* ======================================================================
     3. Stages
     ====================================================================== */
  const live = new Set();      // character controllers on screen
  const has3D = function () { return !!(window.CP3D && window.CP3D.supported()); };

  /* v0.9.5: every character pose is also pre-rendered (scripts/bake_characters.cjs, using this
     same 3D renderer) as a small image. It shows instantly on every load while the live 3D starts,
     and stays if a device cannot run live 3D. A pose without its own image uses that character's
     default image. */
  const STILL_V = '0.9.6-perf1';
  function stillKey(c, xs) {
    const spec = CAST[c.c] || CAST.pip;
    const face = Object.assign(baseFace(spec), c.face || {});
    const text = JSON.stringify([c.c, c.motion || 'idle', c.prop === undefined ? 'none' : c.prop, c.acc || null, xs ? [] : (c.orbs || []).slice(0, 4), face]);
    let h = 2166136261; for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0).toString(16).padStart(8, '0');
  }
  function poseUrl(c, xs) { return `/static/characters/${stillKey(c, xs)}.webp?v=${STILL_V}`; }
  function stillImg(c, xs, cls) {
    const name = CAST[c.c] ? c.c : 'pip';
    return `<img class="cp-still ${cls}" src="${poseUrl(c, xs)}" data-c="${name}" alt="" loading="eager" decoding="async" draggable="false">`;
  }
  document.addEventListener('load', function (event) {
    const img=event.target;
    if(img && img.classList && img.classList.contains('cp-still') && img.parentElement) img.parentElement.dataset.cpReady='1';
  }, true);
  document.addEventListener('error', function (event) {
    const img = event.target;
    if (!img || !img.classList || !img.classList.contains('cp-still')) return;
    if (!img.dataset.generic) { img.dataset.generic = '1'; const ctl = img.parentNode && img.parentNode._ctl; img.src = ctl && ctl.baseSrc && img.getAttribute('src') !== ctl.baseSrc ? ctl.baseSrc : `/static/characters/${img.dataset.c}.webp?v=${STILL_V}`; return; }
    if(img.parentElement) img.parentElement.dataset.cpReady='1';
    img.outerHTML = `<span class="cp-fallback ${img.classList.contains('cp-wait') ? 'cp-wait' : ''}">${(CAST[img.dataset.c] || CAST.pip).emoji}</span>`;
  }, true);
  function baseFace(spec) { return { eyes: 0, mouth: spec.mouth || 0, brow: 0, blush: spec.blush ? 1 : 0 }; }
  function stage(cfg, size) {
    const n = ++uid;
    const confetti = cfg.confetti ? '<div class="cp-confetti">' + Array.from({ length: 14 }, (_, i) => `<i style="--k:${i}"></i>`).join('') + '</div>' : '';
    return `<div class="cp-stage cp-${size}" aria-hidden="true" data-cp-id="${n}" style="--cn:${cfg.chars.length}">
      ${cfg.lines && cfg.lines.length ? '<div class="cp-say"><span class="cp-say-text"></span><i class="cp-caret"></i></div>' : ''}
      <div class="cp-scene">${cfg.chars.map((c, i) => `<div class="cp-char" data-i="${i}" data-c="${c.c}" data-emoji="${(CAST[c.c] || CAST.pip).emoji}"><canvas></canvas>${stillImg(c, /^xs\b/.test(size), 'cp-wait')}</div>`).join('')}${confetti}</div>
    </div>`;
  }
  function attachChars(el, cfg, locked) {
    const ok = has3D();
    el.querySelectorAll('.cp-char').forEach(function (box) {
      const c = cfg.chars[Number(box.dataset.i)];
      const spec = CAST[c.c] || CAST.pip;
      const xs = size(el) === 'xs';
      if (!ok) { imageChar(box, c, xs, locked); return; }
      const still=box.querySelector('img.cp-wait');if(still&&still.complete&&still.naturalWidth)box.dataset.cpReady='1';
      const face = Object.assign(baseFace(spec), c.face || {});
      const ctl = window.CP3D.attach(box.querySelector('canvas'), spec, {
        motion: c.motion || 'idle', prop: c.prop === undefined ? 'none' : c.prop, acc: c.acc, orbs: (c.orbs || []).slice(0, size(el) === 'xs' ? 0 : 4), face: face
      });
      if (!ctl) { imageChar(box, c, xs, locked); return; }
      ctl.cfgChar = c; ctl.xs = xs;
      ctl.base = { motion: ctl.motion, prop: ctl.prop, face: Object.assign({}, face) };
      ctl.locked = !!locked;
      ctl.box = box;
      box._ctl = ctl;
      live.add(ctl);
    });
  }
  /* Pre-rendered 3D character (default). Moods swap to that character's pre-rendered reaction. */
  function imageChar(box, c, xs, locked) {
    // Keep the existing in-flight WebP instead of destroying and requesting it twice.
    let img=box.querySelector('img.cp-wait');
    if(img){const canvas=box.querySelector('canvas');if(canvas)canvas.remove();img.classList.remove('cp-wait','cp-gone');img.classList.add('cp-img');}
    else{box.innerHTML=stillImg(c,xs,'cp-img');img=box.firstElementChild;}
    if(img.complete && img.naturalWidth)box.dataset.cpReady='1';
    const ctl = { img: img, canvas: img, box: box, cfgChar: c, xs: xs, locked: !!locked, baseSrc: poseUrl(c,xs), desiredSrc: poseUrl(c,xs) };
    box._ctl = ctl; live.add(ctl);
  }
  function moodSrc(ctl, mood) { return mood ? `/static/characters/${ctl.img.dataset.c}-${mood}.webp?v=${STILL_V}` : ctl.baseSrc; }
  function size(el) { return el.classList.contains('cp-xs') ? 'xs' : el.classList.contains('cp-sm') ? 'sm' : 'md'; }

  function setMood(ctl, mood) {
    if (ctl.img) {
      const want=moodSrc(ctl,mood);
      if(ctl.desiredSrc===want)return;
      ctl.desiredSrc=want;
      if(ctl.img.getAttribute('src')===want)return;
      // Keep the existing animated character visible while the next reaction loads.
      const next=new Image();next.className=ctl.img.className;next.dataset.c=ctl.img.dataset.c;next.alt='';next.draggable=false;next.decoding='async';
      next.onload=function(){if(ctl.desiredSrc!==want||!ctl.img.isConnected)return;ctl.img.replaceWith(next);ctl.img=ctl.canvas=next;ctl.box.dataset.cpReady='1';};
      next.onerror=function(){}; // a missing reaction must not erase the current character
      next.src=want;return;
    }
    const r = mood ? REACT[mood] : null;
    const b = ctl.base;
    if (!r) { ctl.motion = b.motion; ctl.prop = b.prop; ctl.face = Object.assign({}, b.face); return; }
    ctl.motion = r.motion;
    ctl.prop = r.prop ? r.prop : r.dropProp ? 'none' : b.prop;
    ctl.face = Object.assign({}, b.face, r.face);
    if (r.face.eyes === 2 && b.face.eyes === 2) ctl.face.eyes = 2;
  }
  function applyAll() {
    const c = html.classList;
    const global = c.contains('cp-oops') || c.contains('cp-oops-auth') ? 'oops' : c.contains('cp-cheer') ? 'cheer' : c.contains('cp-sad') ? 'sad' : c.contains('cp-busy') ? 'think' : null;
    live.forEach(function (ctl) {
      if (!ctl.canvas.isConnected) { live.delete(ctl); if (window.CP3D) window.CP3D.detach(ctl); return; }
      let mood = null;
      if (ctl.poke) mood = 'poke';
      else if (ctl.locked) mood = null;
      else if (global) mood = global;
      else if (ctl.box.closest('.cp-voice')) mood = c.contains('cp-talking') ? 'talk' : c.contains('cp-listening') ? 'listen' : null;
      setMood(ctl, mood);
    });
  }

  /* ======================================================================
     4. Speech bubbles
     ====================================================================== */
  const speakers = new Map();
  const BUSY_LINES = ['Thinking… 🤔', 'Reading your material… 📖', 'Connecting the ideas… 🔗', 'Almost there… ⏳'];
  const POKE_LINES = ['Hehe, that tickles! 😆', 'Wheee! 🤸', 'Hi there! 👋', 'Boop! ✨', 'Let’s learn something 🚀'];
  function speak(el, lines, locked) { if (lines && lines.length) speakers.set(el, { lines: lines, index: 0, typed: 0, hold: 0, locked: !!locked }); }
  function overrideLine(s) {
    if (s.poke && Date.now() < s.poke.until) return s.poke.text;
    if (s.locked) return '';
    if (html.classList.contains('cp-busy')) return BUSY_LINES[Math.floor(Date.now() / 2600) % BUSY_LINES.length];
    if (html.classList.contains('cp-cheer')) return 'Yes! Nice work 🎉';
    if (html.classList.contains('cp-sad')) return 'Oops, not that one 😢';
    if (html.classList.contains('cp-oops')) return 'Hmm, something went wrong 🤔';
    return '';
  }
  function setText(box, text) { const n = box.firstChild; if (n && n.nodeType === 3 && !n.nextSibling) { if (n.data !== text) n.data = text; } else box.textContent = text; }
  setInterval(function () {
    if (document.hidden || !speakers.size) return;
    speakers.forEach(function (s, el) {
      if (!el.isConnected) { speakers.delete(el); return; }
      const box = el.querySelector('.cp-say-text');
      if (!box) return;
      const forced = overrideLine(s);
      if (forced) { setText(box, forced); s.forced = true; return; }
      if (s.forced) { s.forced = false; s.typed = 0; }
      const chars = Array.from(s.lines[s.index % s.lines.length]);
      if (s.typed < chars.length) { s.typed += reduce.matches ? chars.length : 1; setText(box, chars.slice(0, s.typed).join('')); return; }
      if (++s.hold > 100) { s.hold = 0; s.typed = 0; s.index += 1; }
    });
  }, 45);

  /* ======================================================================
     5. Mounting on each screen
     ====================================================================== */
  function mount(host, cfg, sizeName, where, locked) {
    host.insertAdjacentHTML(where || 'beforeend', stage(cfg, sizeName));
    const el = where === 'afterbegin' ? host.firstElementChild : host.lastElementChild;
    if (locked) el.classList.add('cp-locked');
    attachChars(el, cfg, locked);
    speak(el, cfg.lines, locked);
    applyAll();
    return el;
  }
  function resultConfig(box) {
    const raw = box.dataset.score;
    const score = raw === '' || raw === undefined ? null : Math.round(Number(raw));
    const t = tier(score);
    const T = TIERS[t];
    return { t: t, score: score, cfg: { chars: T.chars, lines: T.lines(score), confetti: T.confetti } };
  }
  function decorateResult(box) {
    box.dataset.cp = '1';
    const r = resultConfig(box);
    const T = TIERS[r.t];
    const kind = box.dataset.kind === 'viva' ? 'Assigned viva' : box.dataset.kind === 'practice' ? 'Practice viva' : 'Assessment';
    box.classList.add('cp-tier-' + r.t);
    box.innerHTML = `<div class="cp-result-text"><span class="eyebrow">${kind} result</span><strong class="cp-result-score">${r.score === null ? '—' : r.score + '%'}</strong><h2>${T.face} ${T.title}</h2><p>${r.t === 'low' ? 'Below the class average. Your learning path now puts these concepts first.' : r.t === 'pass' ? 'A pass, close to good. One more practice round on the weak topics will lift it.' : r.t === 'pending' ? 'Marks appear here as soon as your teacher confirms them.' : 'Keep the streak going with a quick revision tomorrow.'}</p></div>`;
    mount(box, r.cfg, 'lg', 'afterbegin', true);
    if (r.t === 'top') setTimeout(function () { flash('cp-cheer'); }, 350);
  }
  function one(c, motion, prop, orbs, face) { return { c: c, motion: motion, prop: prop || 'none', orbs: orbs || [], face: face }; }

  function decorate() {
    live.forEach(ctl=>{if(!ctl.canvas.isConnected){live.delete(ctl);if(window.CP3D&&!ctl.img)window.CP3D.detach(ctl);}});
    const result = document.querySelector('#main .cp-result:not([data-cp])');
    if (result) decorateResult(result);
    const hasResult = !!document.querySelector('#main .cp-result');

    document.querySelectorAll('.page-heading:not([data-cp])').forEach(function (h) {
      h.dataset.cp = '1';
      h.classList.add('has-cp');
      if (hasResult) return; // the result card carries the reaction
      const failed = h.parentElement && h.parentElement.querySelector('.error-state');
      const cfg = failed ? { chars: [one('ruby', 'shrug', 'none', [o('orb', 'red'), o('ring', 'blue')], { eyes: 0, mouth: 2, brow: 1 })], lines: ['Oh dear, that did not load 🥺', 'Press "Try again" and I will retry 🔁'] } : screenConfig();
      mount(h, cfg, 'md');
    });
    document.querySelectorAll('.next-card > .orb:not([data-cp])').forEach(function (orb) {
      orb.dataset.cp = '1';
      const holder = document.createElement('div');
      holder.className = 'cp-slot';
      orb.replaceWith(holder);
      mount(holder, { chars: [one('pip', 'point', 'bulb', [o('star', 'gold'), o('orb', 'pink')])] }, 'sm');
    });
    document.querySelectorAll('.voice-center:not([data-cp])').forEach(function (v) {
      v.dataset.cp = '1';
      v.classList.add('cp-voice');
      mount(v, { chars: [role() === 'teacher' ? Object.assign(one('drizzle', 'idle', 'none', [o('ring', 'blue'), o('star', 'gold')]), { acc: ['headphones'] }) : one('coco', 'idle', 'none', [o('star', 'gold'), o('ring', 'purple'), o('heart', 'pink')])] }, 'sm', 'afterbegin');
    });
    document.querySelectorAll('.empty:not([data-cp])').forEach(function (box) {
      box.dataset.cp = '1';
      mount(box, { chars: [one('puff', 'strut', 'magnifier', [o('orb', 'blue'), o('star', 'gold')])] }, 'sm', 'afterbegin');
    });
    document.querySelectorAll('.loading:not([data-cp])').forEach(function (box) {
      box.dataset.cp = '1';
      mount(box, { chars: [one('blip', 'type', 'laptop', [o('gem', 'blue'), o('ring', 'teal')])] }, 'sm');
    });
    document.querySelectorAll('.hero-visual .orbit:not([data-cp])').forEach(function (orbit) {
      orbit.dataset.cp = '1';
      orbit.classList.add('cp-hero');
      orbit.innerHTML = '';
      mount(orbit, { chars: [one('mo', 'present', 'pointer', [o('cube', 'orange'), o('cube', 'blue')]), one('pip', 'wave', 'none', [o('star', 'gold'), o('orb', 'pink')]), one('nova', 'cheer', 'trophy', [o('star', 'gold'), o('gem', 'teal')], { eyes: 2, mouth: 1 })], lines: ["Hi! We're Professor Mo, Pip and Nova 👋", 'Any department. Any course. 🎓', 'Teachers upload a book, we build the practice 📚', 'Tap us — we react! ✨'] }, 'lg');
    });
    document.querySelectorAll('.auth-aside:not([data-cp])').forEach(function (aside) {
      aside.dataset.cp = '1';
      mount(aside, { chars: [one('kiwi', 'wave', 'key', [o('cube', 'blue'), o('star', 'gold')]), one('pip', 'point', 'bulb', [o('orb', 'pink'), o('ring', 'blue')])], lines: ['Welcome to CampusPath 👋', "Students: join with your teacher's code 🔑", 'Teachers: create courses and share enrollment codes 🔑'] }, 'aside');
    });
    document.querySelectorAll('.auth-card:not([data-cp])').forEach(function (card) {
      card.dataset.cp = '1';
      mount(card, { chars: [one('pip', 'wave', 'none', [])] }, 'xs cp-card', 'afterbegin');
    });
    document.querySelectorAll('.sidebar-foot:not([data-cp])').forEach(function (foot) {
      foot.dataset.cp = '1';
      mount(foot, { chars: [one(role() === 'teacher' ? 'mo' : role() === 'admin' ? 'luma' : 'pip', 'idle', 'none', [])] }, 'xs cp-buddy', 'afterbegin');
    });

    const authError = document.querySelector('#auth-error');
    const authBad = !!(authError && authError.textContent.trim());
    if (html.classList.contains('cp-oops-auth') !== authBad) { html.classList.toggle('cp-oops-auth', authBad); applyAll(); }

    // Voice screens: listen while the microphone is on, talk while a question plays.
    const status = document.querySelector('#voice-status');
    const orbEl = document.querySelector('#voice-orb');
    const txt = status ? status.textContent : '';
    const listening = !!(orbEl && orbEl.classList.contains('listening')) || /listening/i.test(txt);
    const talking = /speaking|preparing speech/i.test(txt);
    if (html.classList.contains('cp-listening') !== listening || html.classList.contains('cp-talking') !== talking) {
      html.classList.toggle('cp-listening', listening);
      html.classList.toggle('cp-talking', talking);
      applyAll();
    }
  }

  const warmed=new Set();
  let warmTimer=0,warmRunning=false;
  function warmCharacters(){
    clearTimeout(warmTimer);
    const conn=navigator.connection;
    if(warmRunning||document.hidden||reduce.matches||(conn&&(conn.saveData||/^(slow-)?2g$/.test(conn.effectiveType||''))))return;
    warmTimer=setTimeout(function(){
      if(document.hidden||warmRunning)return;
      if(html.classList.contains('cp-busy')||Array.from(document.querySelectorAll('.cp-char img')).some(img=>!img.complete)){warmCharacters();return;}
      const table=role()==='student'?STUDENT:role()==='teacher'?TEACHER:role()==='admin'?ADMIN:null;
      if(!table)return;
      const urls=Object.values(table).map(r=>poseUrl({c:r[0],motion:r[1],prop:r[2],orbs:r[3],acc:r[5]},false));
      const shown=new Set(Array.from(document.querySelectorAll('.cp-char img'),img=>img.getAttribute('src')));
      shown.forEach(url=>warmed.add(url));
      const url=urls.find(x=>!warmed.has(x));if(!url)return;
      warmed.add(url);warmRunning=true;
      const run=()=>{if(document.hidden){warmRunning=false;warmed.delete(url);return;}
        fetch(url,{credentials:'same-origin',priority:'low'}).then(r=>r.ok?r.arrayBuffer():null).catch(()=>{}).finally(()=>{warmRunning=false;warmCharacters();});};
      if('requestIdleCallback' in window)window.requestIdleCallback(run,{timeout:2000});else setTimeout(run,0);
    },1200);
  }
  document.addEventListener('visibilitychange',function(){html.classList.toggle('cp-hidden',document.hidden);if(!document.hidden)warmCharacters();});
  let scheduled = false;
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(function () { scheduled = false; decorate(); warmCharacters(); });
  }
  /* Perf: decorate() only needs new elements, the voice status/orb and the sign-in error.
     Class changes elsewhere (card tilt, page transitions, reveal) used to re-run it on every
     pointer move and animation step. */
  new MutationObserver(function (records) {
    for (const r of records) {
      const t = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      if (!t || (t.closest && t.closest('.cp-stage'))) continue;
      if (r.type === 'attributes' && t.id !== 'voice-orb') continue;
      if (r.type === 'characterData' && !(t.closest && t.closest('#voice-status, #auth-error'))) continue;
      if(r.type==='childList' && !(t.closest && t.closest('#voice-status, #auth-error')) && !Array.from(r.addedNodes).concat(Array.from(r.removedNodes)).some(n=>n.nodeType===1))continue;
      schedule();
      return;
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class'] });
  schedule();

  /* ======================================================================
     6. Interaction: tap to flip, eyes follow the pointer on desktop
     ====================================================================== */
  document.addEventListener('pointerdown', function (event) {
    const box = event.target.closest && event.target.closest('.cp-char');
    const ctl = box && box._ctl;
    if (!ctl || ctl.poke) return;
    ctl.poke = true; ctl.seed = -performance.now() / 1000; applyAll();
    const st = box.closest('.cp-stage');
    const sp = st && speakers.get(st);
    if (sp) sp.poke = { text: POKE_LINES[Math.floor(Math.random() * POKE_LINES.length)], until: Date.now() + 1800 };
    setTimeout(function () { ctl.poke = false; ctl.seed = Math.random() * 20; applyAll(); }, 1150);
  }, { passive: true });
  let pf = 0, px = 0, py = 0, idleTimer = 0;
  document.addEventListener('pointermove', function (e) {
    if (!finePointer.matches || reduce.matches || !window.CP3D || !Array.from(live).some(ctl=>!ctl.img)) return;
    px = e.clientX; py = e.clientY;
    clearTimeout(idleTimer);
    idleTimer = setTimeout(function () { window.CP3D.pointer(null); }, 2500);
    if (pf) return;
    pf = requestAnimationFrame(function () { pf = 0; window.CP3D.pointer(px, py); });
  }, { passive: true });
  document.addEventListener('pointerleave', function () { if (window.CP3D) window.CP3D.pointer(null); });

  /* ======================================================================
     7. Server activity, success and failure
     ====================================================================== */
  const nativeFetch = window.fetch.bind(window);
  let pending = 0, busyTimer = 0;
  function setBusy() {
    if (pending > 0) {
      if (!busyTimer && !html.classList.contains('cp-busy')) busyTimer = setTimeout(function () { busyTimer = 0; if (pending > 0) { html.classList.add('cp-busy'); applyAll(); } }, 700);
    } else {
      clearTimeout(busyTimer); busyTimer = 0;
      if (html.classList.contains('cp-busy')) { html.classList.remove('cp-busy'); applyAll(); }
    }
  }
  window.fetch = function (input, init) {
    const url = String((input && input.url) || input || '');
    const tracked = url.indexOf('/api/') !== -1 && url.indexOf('/api/health') === -1;
    const request = nativeFetch(input, init);
    if (tracked) {
      pending += 1; setBusy();
      const done = function () { pending = Math.max(0, pending - 1); setBusy(); };
      request.then(done, done);
    }
    return request;
  };

  const negative = /(fail|error|unable|denied|invalid|not |cannot|could not|too large|expired|unavailable|wrong|missing|required)/i;
  let moodTimer = 0;
  function flash(kind) {
    html.classList.remove('cp-cheer', 'cp-oops', 'cp-sad');
    html.classList.add(kind);
    applyAll();
    clearTimeout(moodTimer);
    moodTimer = setTimeout(function () { html.classList.remove(kind); applyAll(); }, 2300);
    if (kind === 'cp-cheer') burst();
  }
  function burst() {
    if (reduce.matches) return;
    document.querySelectorAll('.cp-stage .cp-scene').forEach(function (scene) {
      const r = scene.getBoundingClientRect();
      if (!r.width || r.bottom < 0 || r.top > innerHeight) return;
      const b = document.createElement('div');
      b.className = 'cp-burst';
      b.innerHTML = ['🎉', '⭐', '✨', '🎊', '💫', '✅'].map((x, i) => `<i style="--k:${i}">${x}</i>`).join('');
      scene.appendChild(b);
      setTimeout(function () { b.remove(); }, 1500);
    });
  }
  const toastBox = document.getElementById('toast');
  if (toastBox) {
    let lastFlash = 0;
    new MutationObserver(function () {
      if (toastBox.style.display !== 'block') return;
      if (Date.now() - lastFlash < 400) return;
      lastFlash = Date.now();
      flash(negative.test(toastBox.textContent || '') ? 'cp-oops' : 'cp-cheer');
    }).observe(toastBox, { attributes: true, attributeFilter: ['style'], childList: true, characterData: true, subtree: true });
  }
  window.addEventListener('cp3d-lost', function () {
    const old = Array.from(live); live.clear();
    old.forEach(function (ctl) { if (!ctl.img) imageChar(ctl.box, ctl.cfgChar || { c: ctl.box.dataset.c }, ctl.xs, ctl.locked); });
    applyAll();
  });

  /* Public hooks used by app.js / workflows.js / universal.js and the gallery. */
  window.CampusMascot = {
    react: function (kind) { flash(kind === 'cheer' ? 'cp-cheer' : kind === 'sad' ? 'cp-sad' : 'cp-oops'); },
    tier: tier,
    faceFor: function (score) { return TIERS[tier(score)].face; },
    cast: CAST,
    stillKey: stillKey,
    reactions: REACT, baseFace: baseFace,
    tables: { STUDENT: STUDENT, TEACHER: TEACHER, ADMIN: ADMIN, TIERS: TIERS },
    show: function (host, name, motion, prop, orbs, face) { return mount(host, { chars: [Object.assign(one(name, motion || 'idle', prop || 'none', orbs || []), face ? { face: face } : {})] }, 'md'); }
  };
})();
