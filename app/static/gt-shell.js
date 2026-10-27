/* GrowthTwin shell: one navigation rail, theme and language controls, and ambient effects for every page.
   <script src="gt-shell.js" data-app="spa">  -> main app (index.html): builds only the rail, the app handles the rest
   <script src="gt-shell.js">                 -> standalone pages: builds rail, controls, background effects */
(() => {
  const SPA = document.currentScript && document.currentScript.dataset.app === 'spa';
  const reduce = matchMedia('(prefers-reduced-motion:reduce)').matches;
  const get = k => { try { return localStorage.getItem(k) } catch (e) { return null } };
  const set = (k, v) => { try { localStorage.setItem(k, v) } catch (e) {} };
  const saved = () => (get('gt_lang') === 'en' ? 'en' : 'bn');
  let cur = saved();              // language of the page content
  let lang = SPA ? 'bn' : cur;    // language of the rail (the main app translates its own rail)

  /* Navigation: edit here and every page updates. */
  const NAV = [
    { id: 'top', page: '/', ic: 'sprout', bn: 'হোম', en: 'Home' },
    { id: 'sentinel-monitor', page: '/', ic: 'shield', bn: 'সেন্টিনেল মনিটর', en: 'Sentinel Monitor' },
    { href: '/sentinel.html', ic: 'chart', bn: 'সেন্সর টেলিমেট্রি', en: 'Sensor telemetry', sub: 1 },
    { id: 's1', page: '/', ic: 'bulb', bn: 'চাষের পরামর্শ', en: 'Crop advice' },
    { id: 's2', page: '/', ic: 'cube', bn: 'প্লট টুইন', en: 'Plot twin' },
    { id: 'irrigation', page: '/', ic: 'pulse', bn: 'সেচ কন্ট্রোল', en: 'Irrigation control' },
    { href: '/solarflow.html', ic: 'sun', bn: 'সোলারফ্লো AI', en: 'SolarFlow AI' },
    { id: 's3', page: '/', ic: 'chat', bn: 'WhatsApp / SMS', en: 'WhatsApp / SMS' },
    { id: 's4', page: '/', ic: 'users', bn: 'কৃষকের ভরসা', en: "Farmers' Trust" }
  ];


  /* ---- English to Bangla engine (pages written in English). Dictionary lives in gt-bn.js ---- */
  const GT = window.GT = window.GT || {};
  GT.dict = GT.dict || {};
  const D = GT.dict, ATTR = ['placeholder', 'aria-label', 'title', 'alt'];
  const SKIP = /^(SCRIPT|STYLE|TEXTAREA|CANVAS|NOSCRIPT)$/;
  let RE = null;
  const rx = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const build = () => {
    const keys = Object.keys(D).filter(k => k[0] !== '=' && k.length > 2).sort((a, b) => b.length - a.length);
    RE = keys.length ? new RegExp('(?<![A-Za-z0-9])(?:' + keys.map(rx).join('|') + ')(?![A-Za-z]|-[A-Za-z])', 'g') : null;
  };
  const BD = '০১২৩৪৫৬৭৮৯';
  const digits = s => s.replace(/(?<![A-Za-z_\d]|[A-Za-z]-)\d+(?:\.\d+)?/g, m => m.replace(/\d/g, d => BD[d]));
  const trStr = s => {
    const ws = s.match(/^\s*/)[0], we = s.match(/\s*$/)[0], core = s.trim().replace(/\s+/g, ' ');
    if (!core) return s;
    let out = D[core] != null ? D[core] : D['=' + core];
    if (out == null && core.length <= 600 && /[A-Za-z]/.test(core)) {
      if (!RE) build();
      if (RE) { const r = core.replace(RE, m => D[m]); if (r !== core) out = r; }
    }
    out = digits(out == null ? core : out);
    return out === core ? s : ws + out + we;
  };
  GT.t = s => (cur === 'bn' ? trStr(String(s)) : String(s));
  GT.loc = () => (cur === 'bn' ? 'bn-BD' : undefined);
  Object.defineProperty(GT, 'lang', { get: () => cur });
  GT.add = o => { Object.assign(D, o); RE = null; };

  const tRec = new WeakMap(), aRec = new WeakMap();
  const okNode = n => { for (let p = n.parentNode; p && p.nodeType === 1; p = p.parentNode) { if (SKIP.test(p.nodeName) || p.hasAttribute('data-no-i18n')) return false } return true };
  const fwd = n => {
    if (n.nodeType === 3) {
      const r = tRec.get(n); if (r && n.nodeValue === r.out) return;
      if (!okNode(n)) return;
      const out = trStr(n.nodeValue); if (out !== n.nodeValue) tRec.set(n, { src: n.nodeValue, out }), n.nodeValue = out; else tRec.delete(n);
    } else if (n.nodeType === 1 && !/^(SCRIPT|STYLE)$/.test(n.nodeName)) {
      for (const a of ATTR) {
        const v = n.getAttribute(a); if (v == null) continue;
        const m = aRec.get(n) || {}; if (m[a] && m[a].out === v) continue;
        const out = trStr(v); if (out !== v) { m[a] = { src: v, out }; aRec.set(n, m); n.setAttribute(a, out) } else if (m[a]) delete m[a];
      }
    }
  };
  const back = n => {
    if (n.nodeType === 3) { const r = tRec.get(n); if (r && n.nodeValue === r.out) n.nodeValue = r.src; tRec.delete(n) }
    else if (n.nodeType === 1) { const m = aRec.get(n); if (m) { for (const a in m) if (n.getAttribute(a) === m[a].out) n.setAttribute(a, m[a].src); aRec.delete(n) } }
  };
  const walk = (root, fn) => {
    if (!root) return;
    const w = document.createTreeWalker(root, 1 | 4);
    fn(root);
    let n; while ((n = w.nextNode())) fn(n);
  };
  let roots = [], mo = null, titleSrc = null;
  const watch = () => {
    if (mo) mo.disconnect();
    mo = new MutationObserver(ms => {
      if (cur !== 'bn') return;
      for (const m of ms) {
        if (m.type === 'childList') m.addedNodes.forEach(n => walk(n, fwd));
        else if (m.type === 'characterData') fwd(m.target);
        else fwd(m.target);
      }
    });
    roots.forEach(r => mo.observe(r, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTR }));
  };
  GT.apply = () => {
    roots = (GT.roots || []).map(s => (typeof s === 'string' ? document.querySelector(s) : s)).filter(Boolean);
    if (cur === 'bn') { roots.forEach(r => walk(r, fwd)); if (titleSrc == null) titleSrc = document.title; document.title = trStr(titleSrc) }
    else { roots.forEach(r => walk(r, back)); if (titleSrc != null) document.title = titleSrc }
    watch();
  };
  GT.setContentLang = l => { cur = l; document.documentElement.lang = l; GT.apply() };

  const SPRITE = {
    sprout: '<path d="M12 21v-9"/><path d="M12 12c0-4 3-7 8-7 0 5-3 8-8 7z"/><path d="M12 14c0-3-2-5-6-5 0 4 2 6 6 5z"/>',
    bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
    cube: '<path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M12 12l9-5M12 12L3 7M12 12v10"/>',
    chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/><path d="M9 11h6M9 14h4"/>',
    drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/>',
    shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    out: '<path d="M9 4H5v16h4"/><path d="M16 8l4 4-4 4M20 12H9"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
    users: '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.5 3-6 6-6s6 2.5 6 6"/><path d="M16 5a3 3 0 0 1 0 6M18 14c2 .8 3 3 3 6"/>',
    pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    chart: '<path d="M4 20V4"/><path d="M4 20h16"/><path d="M8 15l3-4 3 2 5-7"/>',
    flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3"/><path d="M8 15h8"/>'
  };
  const sym = k => `<symbol id="i-${k}" viewBox="0 0 24 24">${SPRITE[k]}</symbol>`;
  const missing = Object.keys(SPRITE).filter(k => !document.getElementById('i-' + k));
  if (missing.length) {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('width', '0'); s.setAttribute('height', '0'); s.setAttribute('aria-hidden', 'true');
    s.style.position = 'absolute'; s.innerHTML = '<defs>' + missing.map(sym).join('') + '</defs>';
    document.body.prepend(s);
  }

  const here = location.pathname.replace(/index\.html$/, '') || '/';
  const hrefOf = n => n.href ? n.href : (SPA ? '#' + n.id : '/#' + n.id);
  const isOn = n => n.href ? here === n.href : (SPA ? n.id === 'top' : false);
  const icon = k => `<svg class="ic"><use href="#i-${k}"/></svg>`;

  function rail() {
    const side = document.getElementById('side') || Object.assign(document.createElement('aside'), { id: 'side' });
    side.setAttribute('aria-label', lang === 'en' ? 'Menu' : 'মেনু');
    const L = n => n[lang] || n.bn;
    side.innerHTML =
      `<div class="logo">${icon('sprout')}<span class="l">Growth<b>Twin</b></span></div>` +
      NAV.map(n => `<a href="${hrefOf(n)}"${isOn(n) ? ' class="on" aria-current="page"' : ''}${n.sub ? ' data-sub="1"' : ''} title="${L(n)}" aria-label="${L(n)}">${icon(n.ic)}<span class="l">${L(n)}</span></a>`).join('') +
      (SPA ? `<a href="#x" id="navx" class="hidden" title="বিশেষজ্ঞ / অ্যাডমিন" aria-label="বিশেষজ্ঞ / অ্যাডমিন">${icon('shield')}<span class="l">বিশেষজ্ঞ / অ্যাডমিন</span></a>` +
        `<div id="me" class="hidden"><div class="who"><b id="meName"></b><span id="meRole"></span></div><a href="#" id="out">${icon('out')}<span class="l">বের হন</span></a></div>` : '');
    if (!side.parentNode) document.body.prepend(side);
    return side;
  }

  rail();
  if (SPA) {
    // The main app translates Bangla to English itself. Its Sentinel Monitor view is written in English,
    // so this engine translates that one view to Bangla and restores it when the app switches to English.
    GT.roots = ['#sentinel-monitor'];
    document.addEventListener('gt-lang', e => GT.setContentLang(e.detail === 'en' ? 'en' : 'bn'));
    GT.setContentLang(saved());
    return;
  }

  /* ---- Standalone pages: controls, background, transitions ---- */
  document.body.insertAdjacentHTML('afterbegin',
    '<div id="wipe"></div><div id="fx"><i></i><i></i><i></i></div><div id="spot"></div><canvas id="pt"></canvas>' +
    '<div id="ctl"><button id="lg" type="button" aria-label="Language / ভাষা"></button><button id="th" type="button" aria-label="Day / Night"></button></div>');

  const setTheme = m => {
    document.documentElement.dataset.theme = m; set('gt_theme', m);
    document.getElementById('th').innerHTML = icon(m === 'light' ? 'moon' : 'sun');
    document.dispatchEvent(new CustomEvent('gt-theme', { detail: m }));
  };
  const setLang = l => {
    lang = l; set('gt_lang', l);
    document.getElementById('lg').textContent = l === 'en' ? 'বাং' : 'EN';
    rail(); GT.setContentLang(l);
    document.dispatchEvent(new CustomEvent('gt-lang', { detail: l }));
  };
  document.getElementById('th').onclick = () => setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
  document.getElementById('lg').onclick = () => setLang(cur === 'en' ? 'bn' : 'en');
  setTheme(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');
  GT.roots = [document.body];
  document.getElementById('lg').textContent = cur === 'en' ? 'বাং' : 'EN';
  GT.setContentLang(cur);

  /* wipe transition when moving between pages */
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || a.target || reduce) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin || (u.pathname === location.pathname && u.hash)) return;
    e.preventDefault();
    const w = document.getElementById('wipe'); w.classList.remove('go'); void w.offsetWidth; w.classList.add('go');
    setTimeout(() => { location.href = a.href }, 330);
  });

  /* fireflies, spotlight, card tilt: same as the main app */
  const cv = document.getElementById('pt'), cx = cv.getContext('2d'); let W, H; const ps = [];
  const rs = () => { W = cv.width = innerWidth; H = cv.height = innerHeight }; rs(); addEventListener('resize', rs);
  if (!reduce) {
    for (let i = 0; i < 70; i++) ps.push({ x: Math.random() * W, y: Math.random() * H, r: Math.random() * 2 + .6, v: Math.random() * .4 + .15, p: Math.random() * 6 });
    (function f(t) {
      cx.clearRect(0, 0, W, H); cx.shadowColor = '#a3f20a'; cx.shadowBlur = 12;
      for (const q of ps) {
        q.y -= q.v; q.x += Math.sin(t / 1500 + q.p) * .3; if (q.y < -10) { q.y = H + 10; q.x = Math.random() * W }
        cx.beginPath(); cx.fillStyle = `rgba(190,255,80,${.35 + .35 * Math.sin(t / 600 + q.p)})`; cx.arc(q.x, q.y, q.r, 0, 7); cx.fill();
      }
      requestAnimationFrame(f);
    })(0);
  }
  if (matchMedia('(pointer:fine)').matches && !reduce) {
    const spot = document.getElementById('spot');
    addEventListener('mousemove', e => {
      spot.style.transform = `translate(${e.clientX - 250}px,${e.clientY - 250}px)`;
      const c = e.target.closest && e.target.closest('.card');
      if (c && !c.querySelector('input:focus,textarea:focus,select:focus')) {
        const r = c.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
        c.style.transition = 'transform .12s'; c.style.transform = `perspective(900px) rotateX(${y * -4}deg) rotateY(${x * 5}deg)`;
      }
    });
    document.addEventListener('mouseout', e => {
      const c = e.target.closest && e.target.closest('.card');
      if (c && !c.contains(e.relatedTarget)) { c.style.transition = 'transform .6s'; c.style.transform = '' }
    });
  }
})();
